"""Sprint G — contracts, median signal, no auto-tune."""

from __future__ import annotations

from persona_ai.conversation.behavior_tuning import (
    MIN_SESSIONS_FOR_MEDIAN,
    evaluate_mode_contract,
    mode_metrics_snapshot,
    tuning_note,
    tuning_status,
)


def _row_with_sessions(**overrides):
    base = {
        "mode": "cerita_tong",
        "display_name": "Cerita Tong",
        "turns": 10,
        "interruptions": 0,
        "callback_surfaced": 0,
        "mop_suppressed_events": 0,
        "distributions": {
            "session_count": 3,
            "sessions": {
                "listening_percent": {"median": 76, "p25": 71, "p75": 82, "n": 3},
                "questions": {"median": 1, "p25": 0, "p75": 2, "n": 3},
                "mop_percent": {"median": 0, "p25": 0, "p75": 0, "n": 3},
                "avg_assistant_s": {"median": 1.2, "p25": 0.9, "p75": 1.5, "n": 3},
            },
        },
    }
    base.update(overrides)
    return base


def test_tuning_status_requires_sessions():
    assert (
        tuning_status(turns=10, session_count=1, contract_ok=True) == "insufficient_data"
    )


def test_contract_ok_on_median_cerita_tong():
    health = evaluate_mode_contract(_row_with_sessions())
    assert health["contract_ok"] is True
    assert tuning_status(
        turns=10,
        session_count=MIN_SESSIONS_FOR_MEDIAN,
        contract_ok=True,
    ) == "ok"


def test_contract_fails_listening():
    row = _row_with_sessions(
        distributions={
            "session_count": 2,
            "sessions": {
                "listening_percent": {"median": 51, "p25": 45, "p75": 58, "n": 2},
                "questions": {"median": 7, "n": 2},
                "mop_percent": {"median": 8, "n": 2},
                "avg_assistant_s": {"median": 2.5, "n": 2},
            },
        },
    )
    health = evaluate_mode_contract(row)
    assert health["contract_ok"] is False
    assert "NEEDS_TUNING" in tuning_note("cerita_tong", "needs_tuning", health)


def test_mode_metrics_snapshot():
    snap = mode_metrics_snapshot(_row_with_sessions())
    assert snap["listening_median"] == 76
    assert snap["listening_p25"] == 71
