"""SQLite persistence for open loops — same device DB directory as user memory."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from persona_ai.memory.models import DEFAULT_USER_ID, OpenLoopStatus
from persona_ai.memory.open_loop_models import OpenLoopRecord
from persona_ai.memory.store import default_memory_db_path


class SQLiteOpenLoopStore:
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
                CREATE TABLE IF NOT EXISTS open_loops (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'local',
                    status TEXT NOT NULL DEFAULT 'pending',
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_open_loops_user_status "
                "ON open_loops(user_id, status, updated_at DESC)"
            )
            conn.commit()

    def list_by_status(
        self,
        user_id: str = DEFAULT_USER_ID,
        *,
        status: OpenLoopStatus = "pending",
        limit: int = 50,
    ) -> list[OpenLoopRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM open_loops
                WHERE user_id = ? AND status = ?
                ORDER BY updated_at DESC, rowid DESC
                LIMIT ?
                """,
                (user_id, status, limit),
            ).fetchall()
        return [OpenLoopRecord.from_dict(json.loads(row[0])) for row in rows]

    def get(self, loop_id: str, user_id: str = DEFAULT_USER_ID) -> OpenLoopRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM open_loops WHERE id = ? AND user_id = ?",
                (loop_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return OpenLoopRecord.from_dict(json.loads(row[0]))

    def save(self, record: OpenLoopRecord) -> OpenLoopRecord:
        record.touch()
        payload = json.dumps(record.to_dict(), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO open_loops (id, user_id, status, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    record.id,
                    record.user_id,
                    record.status,
                    payload,
                    record.created_at,
                    record.updated_at,
                ),
            )
            conn.commit()
        return record

    def find_pending_by_topic(
        self,
        topic: str,
        user_id: str = DEFAULT_USER_ID,
    ) -> OpenLoopRecord | None:
        needle = topic.strip().lower()
        if not needle:
            return None
        for record in self.list_by_status(user_id, status="pending", limit=100):
            if record.topic.lower() == needle:
                return record
        return None

    def delete_all(self, user_id: str = DEFAULT_USER_ID) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM open_loops WHERE user_id = ?", (user_id,))
            conn.commit()
            return int(cur.rowcount)

    def close(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA optimize")
                conn.commit()
        except Exception:
            pass
