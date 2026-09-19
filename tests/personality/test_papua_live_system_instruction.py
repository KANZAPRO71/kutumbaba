"""Tests for master Papua Live system instruction (legacy JSON — intentionally disabled)."""

from __future__ import annotations

from persona_ai.personality.papua_live_system_instruction import (
    master_system_instruction_lines,
    master_system_instruction_text,
)


class TestPapuaLiveSystemInstruction:
    def test_master_disabled_to_avoid_verbatim_scripts(self):
        """Master JSON caused repetition — live prompt uses mince/governed builders instead."""
        assert master_system_instruction_lines("papua", display_name="Papua AI") == []
        assert master_system_instruction_text("papua") == ""

    def test_skipped_non_papua(self):
        assert master_system_instruction_lines(None) == []
        assert master_system_instruction_text("jakarta") == ""
