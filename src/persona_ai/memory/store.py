"""SQLite store for user memory — persisted on device (filesDir on Android)."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from persona_ai.memory.models import DEFAULT_USER_ID, UserMemoryRecord


class SQLiteUserMemoryStore:
    """Local durable memory — one row per fact, scoped by user_id."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
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
                CREATE TABLE IF NOT EXISTS user_memory (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'local',
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_memory_user ON user_memory(user_id, updated_at DESC)"
            )
            conn.commit()

    def list_all(
        self,
        user_id: str = DEFAULT_USER_ID,
        *,
        limit: int = 100,
    ) -> list[UserMemoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM user_memory
                WHERE user_id = ?
                ORDER BY updated_at DESC, rowid DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [UserMemoryRecord.from_dict(json.loads(row[0])) for row in rows]

    def get(self, memory_id: str, user_id: str = DEFAULT_USER_ID) -> UserMemoryRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM user_memory WHERE id = ? AND user_id = ?",
                (memory_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return UserMemoryRecord.from_dict(json.loads(row[0]))

    def save(self, record: UserMemoryRecord) -> UserMemoryRecord:
        record.touch()
        payload = json.dumps(record.to_dict(), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_memory (id, user_id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    record.id,
                    record.user_id,
                    payload,
                    record.created_at,
                    record.updated_at,
                ),
            )
            conn.commit()
        return record

    def delete(self, memory_id: str, user_id: str = DEFAULT_USER_ID) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM user_memory WHERE id = ? AND user_id = ?",
                (memory_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def find_similar(
        self,
        content: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> UserMemoryRecord | None:
        needle = content.strip().lower()
        if len(needle) < 4:
            return None
        for record in self.list_all(user_id, limit=200):
            existing = record.content.strip().lower()
            if existing == needle or needle in existing or existing in needle:
                return record
        return None

    def count(self, user_id: str = DEFAULT_USER_ID) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM user_memory WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        """Release SQLite handles — important on Windows before deleting db files."""
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA optimize")
                conn.commit()
        except Exception:
            pass


def default_memory_db_path() -> Path:
    override = (os.environ.get("PERSONA_MEMORY_DB") or "").strip()
    if override:
        return Path(override)
    session_db = (os.environ.get("PERSONA_SESSION_DB") or "").strip()
    if session_db:
        return Path(session_db).with_name("persona_user_memory.db")
    return Path(".persona_ai") / "user_memory.db"
