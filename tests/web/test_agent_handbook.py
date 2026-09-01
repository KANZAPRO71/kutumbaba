"""Tests for Retell-style Agent Handbook presets."""

from __future__ import annotations

from persona_ai.core.types import PersonalityProfile
from persona_ai.web.agent_handbook import AgentHandbookConfig


def test_default_retell_presets() -> None:
    cfg = AgentHandbookConfig()
    assert cfg.default_tone == "professional"
    assert cfg.enable_ai_disclosure is True
    assert cfg.enable_natural_fillers is False
    assert cfg.enable_high_empathy is False


def test_personality_tone_conversational_id() -> None:
    cfg = AgentHandbookConfig(
        default_tone="professional_conversational",
        enable_natural_fillers=True,
        enable_high_empathy=True,
    )
    lines = cfg.personality_tone_lines(language="id", question_budget=0)
    assert any("conversational" in line.lower() for line in lines)
    assert any("filler" in line.lower() for line in lines)
    assert any("frustrasi" in line.lower() for line in lines)
    assert any("jangan menutup dengan pertanyaan check-in" in line for line in lines)
    assert not any("satu pertanyaan per giliran" in line for line in lines)


def test_personality_tone_professional_en() -> None:
    cfg = AgentHandbookConfig(default_tone="professional")
    lines = cfg.personality_tone_lines(language="en")
    assert len(lines) == 1
    assert "Acknowledge" in lines[0]


def test_accuracy_format_presets() -> None:
    cfg = AgentHandbookConfig(
        enable_echo_verification=True,
        enable_nato_phonetic=True,
        enable_speech_normalization_prompt=True,
        enable_smart_matching=True,
    )
    lines = cfg.accuracy_format_lines(language="en")
    assert len(lines) == 4
    assert any("Echo Verification" in line for line in lines)
    assert any("555-0199" in line for line in lines)
    assert any("B as in Bravo" in line for line in lines)
    assert any("twenty-four dollars" in line for line in lines)
    assert any("123 Main St" in line for line in lines)


def test_accuracy_format_presets_id() -> None:
    cfg = AgentHandbookConfig(enable_echo_verification=True, enable_smart_matching=True)
    lines = cfg.accuracy_format_lines(language="id")
    assert any("Echo Verification" in line for line in lines)
    assert any("Smart Matching" in line for line in lines)
    assert any("Jl." in line for line in lines)


def test_trust_safety_presets() -> None:
    cfg = AgentHandbookConfig(enable_ai_disclosure=True, enable_scope_boundaries=True)
    lines = cfg.trust_safety_lines(language="en")
    assert len(lines) == 2
    assert any("AI Disclosure When Asked" in line for line in lines)
    assert any("AI assistant here to help" in line for line in lines)
    assert any("Scope Boundaries" in line for line in lines)
    assert any("connect you to an agent" in line for line in lines)


def test_trust_safety_presets_id() -> None:
    cfg = AgentHandbookConfig(enable_ai_disclosure=True, enable_scope_boundaries=True)
    lines = cfg.trust_safety_lines(language="id")
    assert any("AI Disclosure When Asked" in line for line in lines)
    assert any("Scope Boundaries" in line for line in lines)
    assert any("asisten AI" in line for line in lines)


def test_prompt_sections_grouped() -> None:
    cfg = AgentHandbookConfig(
        default_tone="professional_conversational",
        enable_echo_verification=True,
        enable_ai_disclosure=True,
    )
    sections = cfg.prompt_sections(language="id")
    titles = [title for title, _ in sections]
    assert titles == ["Personality & Tone", "Accuracy & Format", "Trust & Safety"]


def test_from_profile_reads_agent_handbook_block() -> None:
    profile = PersonalityProfile(id="t", preset_id="default_companion", display_name="Persona")
    cfg = AgentHandbookConfig.from_profile(profile)
    assert cfg.default_tone == "companion_friend"
    assert cfg.enable_natural_fillers is True
    assert cfg.enable_high_empathy is True
    assert cfg.enable_ai_disclosure is True
    assert cfg.enable_echo_verification is True
    assert cfg.enable_nato_phonetic is True
    assert cfg.enable_speech_normalization_prompt is True
    assert cfg.enable_smart_matching is True
    assert cfg.enable_scope_boundaries is True
