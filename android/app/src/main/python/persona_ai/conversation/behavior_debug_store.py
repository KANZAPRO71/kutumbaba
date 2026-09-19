"""Local behavior telemetry store — powers Settings → Behavior Debug."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from persona_ai.conversation.behavior_eval import build_behavior_eval
from persona_ai.conversation.experience_modes import normalize_experience_mode
from persona_ai.memory.store import default_memory_db_path

MAX_RECENT_DECISIONS = 40
MAX_EVENTS_PER_DAY = 2000

_store: "BehaviorDebugStore | None" = None


def _today() -> str:
    return date.today().isoformat()


class BehaviorDebugStore:
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
                CREATE TABLE IF NOT EXISTS behavior_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    event TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_behavior_events_day "
                "ON behavior_events(day, id DESC)"
            )
            conn.commit()

    def record(self, namespace: str, event: str, payload: dict[str, Any] | None = None) -> None:
        now = datetime.now(timezone.utc)
        day = now.date().isoformat()
        body = json.dumps(payload or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO behavior_events (day, ts, namespace, event, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (day, now.isoformat(), namespace, event, body),
            )
            conn.execute(
                """
                DELETE FROM behavior_events
                WHERE id NOT IN (
                    SELECT id FROM behavior_events
                    ORDER BY id DESC
                    LIMIT ?
                )
                """,
                (MAX_EVENTS_PER_DAY,),
            )
            conn.commit()

    def _events_for_day(self, day: str | None = None) -> list[dict[str, Any]]:
        key = day or _today()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ts, namespace, event, payload FROM behavior_events
                WHERE day = ?
                ORDER BY id ASC
                """,
                (key,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for ts, namespace, event, payload in rows:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {}
            out.append(
                {
                    "ts": ts,
                    "namespace": namespace,
                    "event": event,
                    "payload": data,
                }
            )
        return out

    def record_turn_decision(self, snapshot: dict[str, Any]) -> None:
        self.record("decision", "turn_decision", snapshot)

    def mop_hold_outcomes_today(self) -> list[dict[str, Any]]:
        """Sprint F prep — hold_ms vs outcome rows for tuning."""
        rows: list[dict[str, Any]] = []
        for ev in self._events_for_day(_today()):
            if ev["namespace"] != "mop" or ev["event"] != "mop_outcome":
                continue
            p = ev["payload"]
            rows.append(
                {
                    "mop_type": p.get("mop_type"),
                    "hold_ms": p.get("planned_hold_ms") or p.get("hold_ms"),
                    "planned_hold_ms": p.get("planned_hold_ms"),
                    "outcome": p.get("outcome"),
                }
            )
        return rows

    def dashboard_for_today(self) -> dict[str, Any]:
        events = self._events_for_day(_today())
        mode_turns: dict[str, int] = {}
        callback = {
            "candidates": 0,
            "selected": 0,
            "surfaced": 0,
            "engaged": 0,
            "suppressed": 0,
        }
        mop = {
            "candidates": 0,
            "selected": 0,
            "suppressed": 0,
            "laugh_reaction": 0,
            "outcomes": {"laughed": 0, "responded": 0, "ignored": 0, "changed_topic": 0},
        }
        cerita = {
            "turns": 0,
            "user_talk_ms": 0,
            "assistant_talk_ms": 0,
            "questions": 0,
            "ack_only": 0,
            "interruptions": 0,
        }
        recent: list[dict[str, Any]] = []

        for ev in events:
            ns = ev["namespace"]
            name = ev["event"]
            p = ev["payload"]
            if ns == "experience" and name == "turn":
                mode = str(p.get("experience_mode") or "unknown")
                mode_turns[mode] = mode_turns.get(mode, 0) + 1
                if mode == "cerita_tong":
                    cerita["turns"] += 1
                    cerita["user_talk_ms"] += int(p.get("user_talk_duration_ms") or 0)
                    cerita["assistant_talk_ms"] += int(p.get("assistant_duration_ms") or 0)
                    cerita["questions"] += int(p.get("question_count") or 0)
                    if p.get("bdv") == "ACK_ONLY":
                        cerita["ack_only"] += 1
                    if p.get("interruption"):
                        cerita["interruptions"] += 1
            if ns == "callback":
                if name == "callback_candidate":
                    callback["candidates"] += 1
                elif name == "callback_selected":
                    callback["selected"] += 1
                elif name == "callback_surfaced":
                    callback["surfaced"] += 1
                elif name == "callback_suppressed":
                    callback["suppressed"] += 1
                elif name == "callback_outcome" and p.get("callback_outcome") == "engaged":
                    callback["engaged"] += 1
            if ns == "mop":
                if name == "mop_candidate":
                    mop["candidates"] += 1
                elif name in ("mop_selected", "mop_setup"):
                    mop["selected"] += 1
                elif name == "mop_suppressed":
                    mop["suppressed"] += 1
                elif name == "mop_reaction" and p.get("reaction") in {
                    "laugh_short",
                    "soft_laugh",
                    "jedag",
                }:
                    mop["laugh_reaction"] += 1
                elif name == "mop_outcome":
                    outcome = str(p.get("outcome") or "")
                    if outcome in mop["outcomes"]:
                        mop["outcomes"][outcome] += 1
            if ns == "decision" and name == "turn_decision":
                recent.append(p)

        total_ct = cerita["user_talk_ms"] + cerita["assistant_talk_ms"]
        cerita["listening_ratio"] = (
            round(cerita["user_talk_ms"] / total_ct, 4) if total_ct > 0 else 0.0
        )
        cerita["listening_percent"] = int(round(cerita["listening_ratio"] * 100))

        eval_data = build_behavior_eval(events)

        return {
            "day": _today(),
            "experience_modes": mode_turns,
            "callback": callback,
            "mop": mop,
            "cerita_tong": cerita,
            "recent_decisions": recent[-MAX_RECENT_DECISIONS:][::-1],
            "mop_hold_outcomes": self.mop_hold_outcomes_today(),
            "eval": eval_data,
        }


def build_turn_decision_snapshot(
    *,
    experience_mode: str | None,
    bdv_speak: str,
    callback: dict[str, Any] | None,
    mop: dict[str, Any] | None,
    session_id: str | None = None,
) -> dict[str, Any]:
    mode = normalize_experience_mode(experience_mode)
    now = datetime.now()
    time_label = now.strftime("%H:%M")

    callback_status = "none"
    callback_reason = ""
    if callback:
        if callback.get("surfaced"):
            callback_status = "selected"
            dec = callback.get("decision") or {}
            callback_reason = str(dec.get("reason") or "surfaced")
        elif callback.get("candidate_count", 0) > 0:
            callback_status = "suppressed"
            callback_reason = str(callback.get("suppressed_reason") or "not_surfaced")
        elif callback.get("suppressed_reason"):
            callback_status = "suppressed"
            callback_reason = str(callback["suppressed_reason"])

    mop_status = "none"
    mop_reason = ""
    mop_phase = ""
    mop_type = ""
    hold_ms = 0
    reaction = ""
    if mop:
        if mop.get("suppressed"):
            mop_status = "suppressed"
            mop_reason = str(mop.get("suppress_reason") or "suppressed")
        elif mop.get("phase") in {"SETUP", "HOLD", "PUNCHLINE", "REACTION"}:
            mop_status = "selected"
            mop_phase = str(mop.get("phase") or "")
            mop_type = str(mop.get("mop_type") or "")
            hold_ms = int(mop.get("hold_ms") or mop.get("timing_delay_ms") or 0)
            reaction = str(mop.get("reaction") or "")
        else:
            mop_status = "idle"

    reason = mop_reason or callback_reason
    if callback_status == "selected" and callback_reason:
        reason = callback_reason
    if mop_status == "selected" and not reason:
        reason = mop_phase.lower() if mop_phase else "mop_active"

    return {
        "time": time_label,
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "experience_mode": mode,
        "bdv": bdv_speak.upper(),
        "callback_status": callback_status,
        "callback_reason": callback_reason,
        "mop_status": mop_status,
        "mop_phase": mop_phase,
        "mop_type": mop_type,
        "hold_ms": hold_ms,
        "reaction": reaction,
        "reason": reason,
    }


def get_behavior_debug_store() -> BehaviorDebugStore:
    global _store
    if _store is None:
        _store = BehaviorDebugStore()
    return _store


def reset_behavior_debug_store() -> None:
    global _store
    _store = None
