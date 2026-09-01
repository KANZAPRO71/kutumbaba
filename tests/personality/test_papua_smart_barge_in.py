"""Tests for smart barge-in filters."""

from __future__ import annotations

from persona_ai.personality.papua_smart_barge_in import (
    is_filler_only,
    should_allow_barge_in,
)


def test_filler_only_rejects_iyo():
    assert is_filler_only("Iyo")
    assert not should_allow_barge_in({}, transcript="Iyo", dialect="papua")


def test_two_word_speech_allowed():
    gov = {"dialect": "papua", "user_speech_started_at": 0.0}
    assert should_allow_barge_in(
        gov,
        transcript="Eh ko stop",
        dialect="papua",
    )


def test_client_rms_allowed_after_short_hold():
    import time

    gov = {"embedded_app": True, "last_forward_at": time.monotonic() - 5.0}
    assert should_allow_barge_in(gov, client_rms=True, dialect="papua")
