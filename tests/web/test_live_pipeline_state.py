from __future__ import annotations

from persona_ai.web.live_pipeline_state import live_pipeline_idle


def test_live_pipeline_idle_when_quiet():
    assert live_pipeline_idle({}) is True
    assert live_pipeline_idle({"ready_for_next_utterance": True}) is True


def test_live_pipeline_idle_false_during_user_activity():
    assert live_pipeline_idle({"user_activity_open": True}) is False


def test_live_pipeline_idle_false_during_gemini_activity():
    assert live_pipeline_idle({"gemini_activity_open": True}) is False
