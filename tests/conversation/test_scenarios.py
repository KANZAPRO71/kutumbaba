"""Tests for conversation mode scenarios."""

from __future__ import annotations

from persona_ai.conversation.mode_prompt import scenario_prompt_lines
from persona_ai.conversation.scenarios import DEFAULT_SCENARIO_ID, get_scenario, list_scenarios
from persona_ai.web.voice_instruction import build_live_voice_instruction
from persona_ai.personality.preset import load_default_preset


def test_list_scenarios_non_empty():
    modes = list_scenarios()
    assert len(modes) >= 5
    assert modes[0].scenario_id == DEFAULT_SCENARIO_ID


def test_unknown_mode_falls_back_to_casual():
    assert get_scenario("not_a_mode").scenario_id == DEFAULT_SCENARIO_ID


def test_curhat_prompt_papua():
    lines = scenario_prompt_lines("curhat", dialect="papua", language="id")
    text = "\n".join(lines)
    assert "MODE OBROLAN" in text
    assert "curhat" in text.lower()


def test_live_instruction_includes_mode():
    profile = load_default_preset()
    instruction = build_live_voice_instruction(
        profile,
        dialect="papua",
        conversation_mode="brainstorm",
    )
    assert "brainstorm" in instruction.lower() or "Brainstorm" in instruction


def test_curhat_natural_extra_in_instruction():
    profile = load_default_preset()
    instruction = build_live_voice_instruction(
        profile,
        dialect="papua",
        conversation_mode="curhat",
    )
    assert "curhat" in instruction.lower()
    assert "solutionizing" in instruction.lower() or "denger" in instruction.lower()
