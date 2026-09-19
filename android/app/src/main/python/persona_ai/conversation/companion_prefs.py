"""User-tunable companion settings — stored locally on device."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from persona_ai.memory.store import default_memory_db_path

DEFAULT_RAG_MIN_SCORE = 0.18


class CompanionPrefs(BaseModel):
    rag_enabled: bool = True
    rag_min_score: float = Field(default=DEFAULT_RAG_MIN_SCORE, ge=0.05, le=0.95)
    rag_use_gemini: bool = False
    updated_at: str = ""


_store: "CompanionPrefsStore | None" = None


class CompanionPrefsStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path or default_memory_db_path())
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=10.0)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS companion_prefs (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    rating TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def load(self) -> CompanionPrefs:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM companion_prefs WHERE id = 1").fetchone()
        if row is None:
            return CompanionPrefs()
        return CompanionPrefs.model_validate(json.loads(row[0]))

    def save(self, prefs: CompanionPrefs) -> CompanionPrefs:
        prefs.updated_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(prefs.model_dump(), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO companion_prefs (id, payload, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
                """,
                (payload, prefs.updated_at),
            )
            conn.commit()
        return prefs

    def record_feedback(self, session_id: str, rating: str) -> None:
        sid = session_id.strip()
        if not sid or rating not in {"up", "down", "skip"}:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO session_feedback (session_id, rating, created_at) VALUES (?, ?, ?)",
                (sid, rating, now),
            )
            conn.commit()

    def feedback_summary(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT rating, COUNT(*) FROM session_feedback GROUP BY rating",
            ).fetchall()
        counts = {"up": 0, "down": 0, "skip": 0}
        for rating, count in rows:
            if rating in counts:
                counts[rating] = int(count)
        return counts

    def list_feedback(self, *, limit: int = 500) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, rating, created_at FROM session_feedback
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 2000)),),
            ).fetchall()
        return [
            {"session_id": sid, "rating": rating, "created_at": created}
            for sid, rating, created in rows
        ]

    def delete_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM companion_prefs")
            conn.execute("DELETE FROM session_feedback")
            conn.commit()


def get_companion_prefs_store() -> CompanionPrefsStore:
    global _store
    if _store is None:
        _store = CompanionPrefsStore()
    return _store


def reset_companion_prefs_store() -> None:
    global _store
    _store = None


def load_companion_prefs() -> CompanionPrefs:
    return get_companion_prefs_store().load()


def save_companion_prefs(prefs: CompanionPrefs) -> CompanionPrefs:
    return get_companion_prefs_store().save(prefs)
