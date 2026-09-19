"""Sprint F — per-mode behavior evaluation aggregates."""

from __future__ import annotations

from persona_ai.conversation.behavior_debug_store import BehaviorDebugStore, reset_behavior_debug_store
from persona_ai.conversation.behavior_eval import build_behavior_eval


def _events_for_eval() -> list[dict]:
    return [
        {
            "namespace": "experience",
            "event": "turn",
            "payload": {
                "experience_mode": "cerita_tong",
                "user_talk_duration_ms": 4000,
                "assistant_duration_ms": 1000,
                "bdv": "ACK_ONLY",
                "question_count": 0,
            },
        },
        {
            "namespace": "experience",
            "event": "turn",
            "payload": {
                "experience_mode": "cerita_tong",
                "user_talk_duration_ms": 3500,
                "assistant_duration_ms": 500,
                "bdv": "DEFER",
                "question_count": 1,
            },
        },
        {
            "namespace": "experience",
            "event": "turn",
            "payload": {
                "experience_mode": "mop",
                "user_talk_duration_ms": 2000,
                "assistant_duration_ms": 3000,
                "bdv": "RESPOND",
                "question_count": 0,
            },
        },
        {
            "namespace": "decision",
            "event": "turn_decision",
            "payload": {
                "experience_mode": "mop",
                "bdv": "RESPOND",
                "mop_status": "selected",
                "mop_phase": "SETUP",
                "mop_type": "observational",
            },
        },
        {
            "namespace": "mop",
            "event": "mop_setup",
            "payload": {"mop_type": "observational"},
        },
        {
            "namespace": "mop",
            "event": "mop_suppressed",
            "payload": {"experience_mode": "mop", "reason": "cooldown_active"},
        },
        {
            "namespace": "mop",
            "event": "mop_outcome",
            "payload": {
                "outcome": "laughed",
                "planned_hold_ms": 350,
                "mop_type": "observational",
            },
        },
        {
            "namespace": "callback",
            "event": "callback_surfaced",
            "payload": {"experience_mode": "nongkrong", "loop_id": "x"},
        },
        {
            "namespace": "callback",
            "event": "callback_followed_up",
            "payload": {"callback_outcome": "engaged", "loop_id": "x"},
        },
    ]


def test_build_behavior_eval_mode_table():
    ev = build_behavior_eval(_events_for_eval())
    cerita = next(r for r in ev["mode_table"] if r["mode"] == "cerita_tong")
    assert cerita["turns"] == 2
    assert cerita["listening_percent"] == 83
    assert cerita["questions"] == 1
    assert cerita["bdv_distribution"]["ACK_ONLY"] == 1
    assert cerita["bdv_distribution"]["DEFER"] == 1

    mop_row = next(r for r in ev["mode_table"] if r["mode"] == "mop")
    assert mop_row["turns"] == 1
    assert mop_row["mop_percent"] == 100


def test_decision_outcomes_and_planned_hold():
    ev = build_behavior_eval(_events_for_eval())
    decisions = {d["decision"]: d for d in ev["decision_outcomes"]}
    assert decisions["CALLBACK surfaced"]["count"] == 1
    assert decisions["CALLBACK surfaced"]["followed_count"] == 1
    assert decisions["MOP suppressed"]["count"] >= 1

    hold = {r["planned_hold_ms"]: r for r in ev["planned_hold_outcomes"]}
    assert hold[350]["total"] == 1
    assert hold[350]["engaged_percent"] == 100
    assert "Planned Hold" in ev["planned_hold_label"]


def test_session_distribution_from_summaries():
    events = _events_for_eval() + [
        {
            "namespace": "experience",
            "event": "session_summary",
            "payload": {
                "session_id": "s-a",
                "experience_mode": "cerita_tong",
                "turns": 2,
                "listening_percent": 95,
                "avg_assistant_s": 0.5,
                "questions": 0,
                "mop_percent": 0,
                "callback_surfaced": 0,
            },
        },
        {
            "namespace": "experience",
            "event": "session_summary",
            "payload": {
                "session_id": "s-b",
                "experience_mode": "cerita_tong",
                "turns": 3,
                "listening_percent": 45,
                "avg_assistant_s": 2.1,
                "questions": 4,
                "mop_percent": 10,
                "callback_surfaced": 0,
            },
        },
    ]
    ev = build_behavior_eval(events)
    cerita = next(r for r in ev["mode_table"] if r["mode"] == "cerita_tong")
    dist = cerita.get("distributions") or {}
    assert dist.get("session_count") == 2
    listen = dist.get("sessions", {}).get("listening_percent") or {}
    assert listen.get("n") == 2
    assert listen.get("min") == 45.0
    assert listen.get("max") == 95.0
    assert cerita.get("tuning_status") in {"ok", "needs_tuning", "insufficient_data"}


def test_dashboard_includes_eval(tmp_path, monkeypatch):
    db = tmp_path / "eval.db"
    monkeypatch.setenv("PERSONA_MEMORY_DB", str(db))
    reset_behavior_debug_store()
    store = BehaviorDebugStore(db)
    for item in _events_for_eval():
        store.record(item["namespace"], item["event"], item["payload"])
    dash = store.dashboard_for_today()
    assert "eval" in dash
    assert len(dash["eval"]["mode_table"]) == 5
