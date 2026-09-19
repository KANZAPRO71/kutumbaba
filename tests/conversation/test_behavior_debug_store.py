"""Sprint E — behavior debug store + dashboard."""

from __future__ import annotations

import pytest

from persona_ai.conversation.behavior_debug_store import (
    BehaviorDebugStore,
    build_turn_decision_snapshot,
    reset_behavior_debug_store,
)


@pytest.fixture
def debug_store(tmp_path, monkeypatch):
    db = tmp_path / "behavior.db"
    monkeypatch.setenv("PERSONA_MEMORY_DB", str(db))
    reset_behavior_debug_store()
    store = BehaviorDebugStore(db)
    yield store
    reset_behavior_debug_store()


def test_dashboard_aggregates_today(debug_store: BehaviorDebugStore):
    debug_store.record(
        "experience",
        "turn",
        {
            "experience_mode": "nongkrong",
            "user_talk_duration_ms": 1200,
            "assistant_duration_ms": 800,
            "bdv": "RESPOND",
            "question_count": 0,
        },
    )
    debug_store.record(
        "experience",
        "turn",
        {
            "experience_mode": "cerita_tong",
            "user_talk_duration_ms": 3000,
            "assistant_duration_ms": 500,
            "bdv": "ACK_ONLY",
            "question_count": 0,
        },
    )
    debug_store.record("callback", "callback_candidate", {"loop_id": "a"})
    debug_store.record("callback", "callback_selected", {"loop_id": "a"})
    debug_store.record("callback", "callback_surfaced", {"loop_id": "a"})
    debug_store.record("mop", "mop_candidate", {})
    debug_store.record("mop", "mop_suppressed", {"reason": "mode_mop_off"})
    debug_store.record(
        "mop",
        "mop_outcome",
        {"outcome": "laughed", "planned_hold_ms": 350, "mop_type": "observational"},
    )

    snap = build_turn_decision_snapshot(
        experience_mode="cerita_tong",
        bdv_speak="ack_only",
        callback={"candidate_count": 1, "surfaced": False, "suppressed_reason": "bdv_silence"},
        mop={"suppressed": True, "suppress_reason": "mode_disallows"},
    )
    debug_store.record_turn_decision(snap)

    dash = debug_store.dashboard_for_today()
    assert dash["experience_modes"]["nongkrong"] == 1
    assert dash["experience_modes"]["cerita_tong"] == 1
    assert dash["callback"]["candidates"] == 1
    assert dash["callback"]["selected"] == 1
    assert dash["callback"]["surfaced"] == 1
    assert dash["mop"]["candidates"] == 1
    assert dash["mop"]["suppressed"] == 1
    assert dash["cerita_tong"]["ack_only"] == 1
    assert dash["cerita_tong"]["listening_percent"] == 86
    assert len(dash["recent_decisions"]) == 1
    assert dash["recent_decisions"][0]["bdv"] == "ACK_ONLY"
    assert len(dash["mop_hold_outcomes"]) == 1
    assert dash["mop_hold_outcomes"][0]["hold_ms"] == 350
    assert "eval" in dash
    assert isinstance(dash["eval"].get("mode_table"), list)
