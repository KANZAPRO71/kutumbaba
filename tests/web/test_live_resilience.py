"""Tests for live link-state helpers (pillar 4)."""

from persona_ai.web.live_resilience import (
    LINK_CONNECTED,
    LINK_DISCONNECTED,
    LINK_RESUMING,
    LINK_SUSPENDED,
    emit_link_state,
    gov_link_state,
    gov_set_link_state,
    map_resume_to_link_states,
)


def test_map_resume_to_link_states():
    from persona_ai.web.live_resilience import LINK_LIVE

    assert map_resume_to_link_states(starting=True, success=False, fatal=False) == [
        LINK_RESUMING,
        LINK_SUSPENDED,
    ]
    assert map_resume_to_link_states(starting=False, success=True, fatal=False) == [
        LINK_LIVE,
        LINK_CONNECTED,
    ]
    assert map_resume_to_link_states(starting=False, success=False, fatal=True) == [
        LINK_DISCONNECTED,
    ]


def test_gov_link_state_and_emit():
    gov: dict = {}
    assert gov_link_state(gov) == LINK_CONNECTED
    gov_set_link_state(gov, LINK_SUSPENDED)
    assert gov_link_state(gov) == LINK_SUSPENDED

    out: list[dict] = []

    def enqueue(payload: dict) -> None:
        out.append(payload)

    emit_link_state(enqueue, LINK_RESUMING, detail="test")
    assert out == [{"type": "link_state", "state": LINK_RESUMING, "detail": "test"}]
