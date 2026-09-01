"""Session persistence stores — SessionStore protocol + implementations."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Protocol

from persona_ai.session.models import SessionState, deserialize_session, serialize_session


class SessionStore(Protocol):
    def load(self, session_id: str) -> SessionState | None: ...

    def save(self, session: SessionState) -> None: ...

    def delete(self, session_id: str) -> None: ...


class InMemorySessionStore:
    """Ephemeral store — tests and pipeline_v0 compat default."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def load(self, session_id: str) -> SessionState | None:
        state = self._sessions.get(session_id)
        if state is None:
            return None
        return state.model_copy(deep=True)

    def save(self, session: SessionState) -> None:
        self._sessions[session.session_id] = session.model_copy(deep=True)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def latest_with_messages(self) -> SessionState | None:
        best: SessionState | None = None
        for state in self._sessions.values():
            if not state.messages:
                continue
            if best is None or state.updated_at >= best.updated_at:
                best = state
        return best.model_copy(deep=True) if best else None


class SQLiteSessionStore:
    """Local transactional session store — MVP default for production use."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def load(self, session_id: str) -> SessionState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        return deserialize_session(data)

    def save(self, session: SessionState) -> None:
        payload = json.dumps(serialize_session(session), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (session.session_id, payload, session.updated_at),
            )
            conn.commit()

    def delete(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()

    def latest_with_messages(self) -> SessionState | None:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM sessions ORDER BY updated_at DESC, rowid DESC LIMIT 20"
            ).fetchall()
        for row in rows:
            session = deserialize_session(json.loads(row[0]))
            if session.messages:
                return session
        return None


def default_db_path() -> Path:
    override = (os.environ.get("PERSONA_SESSION_DB") or "").strip()
    if override:
        return Path(override)
    return Path(".persona_ai") / "sessions.db"
