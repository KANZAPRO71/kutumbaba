"""Tests for agent timezone / current time awareness."""

from __future__ import annotations

from persona_ai.core.types import PersonalityProfile
from persona_ai.web.time_awareness import (
    TimeAwarenessConfig,
    normalize_timezone,
)


def test_normalize_timezone_iana_and_aliases() -> None:
    assert normalize_timezone("Asia/Jakarta") == "Asia/Jakarta"
    assert normalize_timezone("WIB") == "Asia/Jakarta"
    assert normalize_timezone("WITA") == "Asia/Makassar"
    assert normalize_timezone("") is None
    assert normalize_timezone("Not/A/Zone") is None


def test_unset_timezone_prompts_caution() -> None:
    cfg = TimeAwarenessConfig()
    assert cfg.is_set is False
    line = cfg.current_datetime_line(language="en")
    assert "no agent timezone set" in line.lower()
    answer = cfg.time_answer(language="en")
    assert "can't give a precise local time" in answer.lower()
    assert cfg.interpretation_lines() == []


def test_set_timezone_includes_clock_and_relative_rules() -> None:
    cfg = TimeAwarenessConfig(timezone="Asia/Jakarta")
    assert cfg.is_set is True
    now = cfg.now()
    assert now is not None
    assert now.tzinfo is not None

    line = cfg.current_datetime_line(language="id")
    assert "Asia/Jakarta" in line
    assert "Waktu lokal sekarang" in line

    rules = cfg.interpretation_lines(language="id")
    assert len(rules) == 1
    assert "hari ini" in rules[0]
    assert "besok" in rules[0]

    en_rules = cfg.interpretation_lines(language="en")
    assert "today" in en_rules[0].lower()
    assert "tomorrow" in en_rules[0].lower()


def test_from_profile_reads_preset_timezone() -> None:
    profile = PersonalityProfile(id="t", preset_id="default_companion", display_name="Persona")
    cfg = TimeAwarenessConfig.from_profile(profile)
    assert cfg.timezone == "Asia/Jakarta"


def test_prompt_lines_in_system_prompt_shape() -> None:
    cfg = TimeAwarenessConfig(timezone="UTC")
    lines = cfg.prompt_lines(language="en")
    assert len(lines) == 2
    assert lines[0].startswith("Current Time Awareness:")
