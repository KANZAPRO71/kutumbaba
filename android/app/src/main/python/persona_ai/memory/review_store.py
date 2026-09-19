"""SQLite queue for LLM-suggested facts pending user confirm."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from persona_ai.memory.models import DEFAULT_USER_ID
from persona_ai.memory.review_models import MemoryReviewRecord
from persona_ai.memory.store import default_memory_db_path


class SQLiteMemoryReviewStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path or default_memory_db_path())
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=DELETE")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_review (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'local',
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_review_user ON memory_review(user_id, created_at DESC)"
            )
            conn.commit()

    def list_all(
        self,
        user_id: str = DEFAULT_USER_ID,
        *,
        limit: int = 50,
    ) -> list[MemoryReviewRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM memory_review
                WHERE user_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [MemoryReviewRecord.from_dict(json.loads(row[0])) for row in rows]

    def get(self, review_id: str, user_id: str = DEFAULT_USER_ID) -> MemoryReviewRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM memory_review WHERE id = ? AND user_id = ?",
                (review_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return MemoryReviewRecord.from_dict(json.loads(row[0]))

    def save(self, record: MemoryReviewRecord) -> MemoryReviewRecord:
        if not record.created_at:
            record.created_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(record.to_dict(), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_review (id, user_id, payload, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload
                """,
                (record.id, record.user_id, payload, record.created_at),
            )
            conn.commit()
        return record

    def delete(self, review_id: str, user_id: str = DEFAULT_USER_ID) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM memory_review WHERE id = ? AND user_id = ?",
                (review_id, user_id),
            )
            conn.commit()
            return int(cur.rowcount) > 0

    def delete_all(self, user_id: str = DEFAULT_USER_ID) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM memory_review WHERE user_id = ?", (user_id,))
            conn.commit()
            return int(cur.rowcount)

    def close(self) -> None:
        try:
            with self._connect() as conn:
                conn.commit()
        except Exception:
            pass
