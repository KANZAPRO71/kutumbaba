"""Tests for Retell Call Settings mapping."""

from __future__ import annotations

from persona_ai.core.types import PersonalityProfile
from persona_ai.web.call_config import LiveCallConfig


def test_defaults_match_retell_call_settings() -> None:
    cfg = LiveCallConfig()
    assert cfg.end_call_on_silence_ms == 600_000
    assert cfg.max_call_duration_ms == 3_600_000
    assert cfg.keypad_timeout_ms == 2500
    assert cfg.ring_duration_ms == 30_000
    assert not cfg.enable_voicemail_detection
    assert not cfg.enable_keypad_detection


def test_keypad_termination_and_digit_limit() -> None:
    term = LiveCallConfig(keypad_termination_key="#")
    done, payload = term.keypad_complete("123#", latest_digit="#")
    assert done is True
    assert payload == "123"

    limit = LiveCallConfig(keypad_digit_limit=4)
    done, payload = limit.keypad_complete("12345", latest_digit="5")
    assert done is True
    assert payload == "1234"


def test_from_profile_reads_live_call_block() -> None:
    profile = PersonalityProfile(id="t", preset_id="default_companion", display_name="Persona")
    cfg = LiveCallConfig.from_profile(profile)
    assert cfg.end_call_on_silence_ms == 600_000
    assert cfg.max_call_duration_ms == 3_600_000
    assert cfg.keypad_timeout_ms == 2500
