"""Local companion usage stats — streaks without cloud analytics."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from persona_ai.memory.store import default_memory_db_path
from pydantic import BaseModel, Field


class CompanionStats(BaseModel):
    streak_days: int = 0
    last_talk_date: str = ""
    total_sessions: int = 0
    total_duration_ms: int = 0
    updated_at: str = ""


_store: "CompanionStatsStore | None" = None


class CompanionStatsStore:
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
                CREATE TABLE IF NOT EXISTS companion_stats (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def load(self) -> CompanionStats:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM companion_stats WHERE id = 1").fetchone()
        if row is None:
            return CompanionStats()
        return CompanionStats.model_validate(json.loads(row[0]))

    def save(self, stats: CompanionStats) -> CompanionStats:
        stats.updated_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(stats.model_dump(), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO companion_stats (id, payload, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
                """,
                (payload, stats.updated_at),
            )
            conn.commit()
        return stats

    def delete_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM companion_stats")
            conn.commit()

    def record_session(self, *, duration_ms: int = 0) -> CompanionStats:
        stats = self.load()
        today = date.today().isoformat()
        yesterday = date.fromordinal(date.today().toordinal() - 1).isoformat()

        if stats.last_talk_date == today:
            pass
        elif stats.last_talk_date == yesterday:
            stats.streak_days = max(1, stats.streak_days) + 1
        else:
            stats.streak_days = 1

        stats.last_talk_date = today
        stats.total_sessions += 1
        stats.total_duration_ms += max(0, int(duration_ms))
        return self.save(stats)


def get_companion_stats_store() -> CompanionStatsStore:
    global _store
    if _store is None:
        _store = CompanionStatsStore()
    return _store


def reset_companion_stats_store() -> None:
    global _store
    _store = None


def record_companion_session(*, duration_ms: int = 0) -> CompanionStats:
    return get_companion_stats_store().record_session(duration_ms=duration_ms)


def load_companion_stats() -> CompanionStats:
    return get_companion_stats_store().load()


def stats_for_client(stats: CompanionStats) -> dict[str, int | str | list]:
    from persona_ai.conversation.companion_achievements import achievements_for_client

    minutes = stats.total_duration_ms // 60_000
    return {
        "streak_days": stats.streak_days,
        "last_talk_date": stats.last_talk_date,
        "total_sessions": stats.total_sessions,
        "minutes_talked": minutes,
        "achievements": achievements_for_client(stats),
    }
