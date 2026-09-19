"""Behavior config revision — tags telemetry snapshots (no auto config changes)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from persona_ai.memory.store import default_memory_db_path

_META_REVISION = "behavior_config_revision_num"
_META_EXPERIMENT_SEQ = "behavior_experiment_seq"


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or default_memory_db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS behavior_config_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    return conn


def _meta_get(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute(
        "SELECT value FROM behavior_config_meta WHERE key = ?", (key,)
    ).fetchone()
    return row[0] if row else default


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO behavior_config_meta (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _next_int(conn: sqlite3.Connection, key: str) -> int:
    raw = _meta_get(conn, key, "0")
    try:
        n = int(raw)
    except ValueError:
        n = 0
    n += 1
    _meta_set(conn, key, str(n))
    return n


def format_revision(n: int) -> str:
    return f"g.{n:03d}"


def format_experiment_id(n: int) -> str:
    return f"exp_{n:03d}"


def current_revision(db_path: str | Path | None = None) -> str:
    with _connect(db_path) as conn:
        raw = _meta_get(conn, _META_REVISION, "1")
        try:
            n = int(raw)
        except ValueError:
            n = 1
        if not conn.execute(
            "SELECT 1 FROM behavior_config_meta WHERE key = ?", (_META_REVISION,)
        ).fetchone():
            _meta_set(conn, _META_REVISION, "1")
            conn.commit()
            return format_revision(1)
        conn.commit()
        return format_revision(n)


def bump_revision(db_path: str | Path | None = None) -> str:
    """Call after human applies a behavior config change (one lever)."""
    with _connect(db_path) as conn:
        n = _next_int(conn, _META_REVISION)
        conn.commit()
        return format_revision(n)


def next_experiment_id(db_path: str | Path | None = None) -> str:
    with _connect(db_path) as conn:
        n = _next_int(conn, _META_EXPERIMENT_SEQ)
        conn.commit()
        return format_experiment_id(n)


def stamp_metrics(metrics: dict, revision: str) -> dict:
    out = dict(metrics)
    out["config_revision"] = revision
    return out
