"""Sprint G — controlled behavior experiments (before/after snapshots, no auto-tune)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from persona_ai.conversation.behavior_config_revision import (
    current_revision,
    next_experiment_id,
    stamp_metrics,
)
from persona_ai.memory.store import default_memory_db_path

ExperimentStatus = Literal["active", "completed", "reverted"]

_store: "BehaviorExperimentStore | None" = None


class BehaviorExperimentStore:
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
                CREATE TABLE IF NOT EXISTS behavior_experiments (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    mode TEXT NOT NULL,
                    lever TEXT NOT NULL,
                    before_value TEXT NOT NULL,
                    after_value TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    status TEXT NOT NULL,
                    before_metrics TEXT NOT NULL,
                    after_metrics TEXT,
                    config_revision_before TEXT,
                    config_revision_after TEXT
                )
                """
            )
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(behavior_experiments)").fetchall()
            }
            if "config_revision_before" not in cols:
                conn.execute(
                    "ALTER TABLE behavior_experiments ADD COLUMN config_revision_before TEXT"
                )
            if "config_revision_after" not in cols:
                conn.execute(
                    "ALTER TABLE behavior_experiments ADD COLUMN config_revision_after TEXT"
                )
            conn.commit()

    def create(
        self,
        *,
        mode: str,
        lever: str,
        before_value: str,
        after_value: str,
        hypothesis: str,
        before_metrics: dict[str, Any],
        config_revision_before: str | None = None,
    ) -> dict[str, Any]:
        exp_id = next_experiment_id(self._db_path)
        rev_before = config_revision_before or current_revision(self._db_path)
        metrics = stamp_metrics(before_metrics, rev_before)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO behavior_experiments (
                    id, created_at, mode, lever, before_value, after_value,
                    hypothesis, status, before_metrics, after_metrics,
                    config_revision_before, config_revision_after
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exp_id,
                    now,
                    mode,
                    lever,
                    before_value,
                    after_value,
                    hypothesis,
                    "active",
                    json.dumps(metrics, ensure_ascii=False),
                    None,
                    rev_before,
                    None,
                ),
            )
            conn.commit()
        return self.get(exp_id) or {}

    def list_all(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, completed_at, mode, lever, before_value,
                       after_value, hypothesis, status, before_metrics, after_metrics,
                       config_revision_before, config_revision_after
                FROM behavior_experiments
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get(self, exp_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, created_at, completed_at, mode, lever, before_value,
                       after_value, hypothesis, status, before_metrics, after_metrics,
                       config_revision_before, config_revision_after
                FROM behavior_experiments WHERE id = ?
                """,
                (exp_id,),
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def complete(
        self,
        exp_id: str,
        *,
        after_metrics: dict[str, Any],
        status: ExperimentStatus = "completed",
        config_revision_after: str | None = None,
    ) -> dict[str, Any] | None:
        rev_after = config_revision_after or current_revision(self._db_path)
        metrics = stamp_metrics(after_metrics, rev_after)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE behavior_experiments
                SET completed_at = ?, after_metrics = ?, status = ?,
                    config_revision_after = ?
                WHERE id = ?
                """,
                (
                    now,
                    json.dumps(metrics, ensure_ascii=False),
                    status,
                    rev_after,
                    exp_id,
                ),
            )
            conn.commit()
        return self.get(exp_id)

    @staticmethod
    def _row_to_dict(row: tuple) -> dict[str, Any]:
        if len(row) == 11:
            (
                exp_id,
                created_at,
                completed_at,
                mode,
                lever,
                before_value,
                after_value,
                hypothesis,
                status,
                before_metrics,
                after_metrics,
            ) = row
            rev_before = None
            rev_after = None
        else:
            (
                exp_id,
                created_at,
                completed_at,
                mode,
                lever,
                before_value,
                after_value,
                hypothesis,
                status,
                before_metrics,
                after_metrics,
                rev_before,
                rev_after,
            ) = row
        return {
            "experiment_id": exp_id,
            "id": exp_id,
            "created_at": created_at,
            "completed_at": completed_at,
            "mode": mode,
            "lever": lever,
            "before_value": before_value,
            "after_value": after_value,
            "hypothesis": hypothesis,
            "status": status,
            "before_metrics": json.loads(before_metrics or "{}"),
            "after_metrics": json.loads(after_metrics) if after_metrics else None,
            "config_revision_before": rev_before
            or json.loads(before_metrics or "{}").get("config_revision"),
            "config_revision_after": rev_after,
        }

    def patch_revision_after(self, exp_id: str, revision: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE behavior_experiments SET config_revision_after = ? WHERE id = ?
                """,
                (revision, exp_id),
            )
            conn.commit()
        return self.get(exp_id)


def get_behavior_experiment_store() -> BehaviorExperimentStore:
    global _store
    if _store is None:
        _store = BehaviorExperimentStore()
    return _store


def reset_behavior_experiment_store() -> None:
    global _store
    _store = None
