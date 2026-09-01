"""Tests for live_mode natural vs governed."""

from __future__ import annotations

from persona_ai.core.types import PersonalityProfile
from persona_ai.web.live_mode import LiveModeConfig


def test_default_is_natural() -> None:
    cfg = LiveModeConfig()
    assert cfg.is_natural is True
    assert cfg.response_policy() == "live_voice_natural"


def test_governed_mode() -> None:
    cfg = LiveModeConfig(mode="governed")
    assert cfg.is_governed is True
    assert cfg.response_policy() == "live_voice"


def test_from_profile_reads_preset() -> None:
    profile = PersonalityProfile(id="t", preset_id="default_companion", display_name="Persona")
    cfg = LiveModeConfig.from_profile(profile)
    assert cfg.mode == "natural"
