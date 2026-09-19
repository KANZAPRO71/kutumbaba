"""Daily callback budget — max one surfaced callback per calendar day."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from persona_ai.memory.store import default_memory_db_path


@dataclass
class CallbackDailyState:
    day: str
    candidate_count: int = 0
    selected_count: int = 0
    surfaced_count: int = 0
    last_surfaced_loop_id: str | None = None
    last_surfaced_at: str | None = None
    pending_outcome_loop_id: str | None = None


_store: "CallbackDailyStore | None" = None


class CallbackDailyStore:
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
                CREATE TABLE IF NOT EXISTS callback_daily (
                    day TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _today(self) -> str:
        return date.today().isoformat()

    def load(self, day: str | None = None) -> CallbackDailyState:
        key = day or self._today()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM callback_daily WHERE day = ?", (key,)
            ).fetchone()
        if row is None:
            return CallbackDailyState(day=key)
        data = json.loads(row[0])
        return CallbackDailyState(
            day=key,
            candidate_count=int(data.get("candidate_count") or 0),
            selected_count=int(data.get("selected_count") or 0),
            surfaced_count=int(data.get("surfaced_count") or 0),
            last_surfaced_loop_id=data.get("last_surfaced_loop_id"),
            last_surfaced_at=data.get("last_surfaced_at"),
            pending_outcome_loop_id=data.get("pending_outcome_loop_id"),
        )

    def save(self, state: CallbackDailyState) -> CallbackDailyState:
        payload = json.dumps(
            {
                "candidate_count": state.candidate_count,
                "selected_count": state.selected_count,
                "surfaced_count": state.surfaced_count,
                "last_surfaced_loop_id": state.last_surfaced_loop_id,
                "last_surfaced_at": state.last_surfaced_at,
                "pending_outcome_loop_id": state.pending_outcome_loop_id,
            },
            ensure_ascii=False,
        )
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO callback_daily (day, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
                """,
                (state.day, payload, now),
            )
            conn.commit()
        return state

    def increment_candidates(self, n: int = 1) -> CallbackDailyState:
        state = self.load()
        state.candidate_count += max(0, n)
        return self.save(state)

    def increment_selected(self) -> CallbackDailyState:
        state = self.load()
        state.selected_count += 1
        return self.save(state)

    def record_surfaced(self, loop_id: str) -> CallbackDailyState:
        state = self.load()
        state.surfaced_count += 1
        state.last_surfaced_loop_id = loop_id
        state.last_surfaced_at = datetime.now(timezone.utc).isoformat()
        state.pending_outcome_loop_id = loop_id
        return self.save(state)

    def clear_pending_outcome(self) -> CallbackDailyState:
        state = self.load()
        state.pending_outcome_loop_id = None
        return self.save(state)

    def surfaced_today(self) -> int:
        return self.load().surfaced_count


def get_callback_daily_store() -> CallbackDailyStore:
    global _store
    if _store is None:
        _store = CallbackDailyStore()
    return _store


def reset_callback_daily_store() -> None:
    global _store
    _store = None
