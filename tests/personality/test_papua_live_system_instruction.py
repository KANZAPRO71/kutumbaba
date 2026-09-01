"""Tests for master Papua Live system instruction."""

from __future__ import annotations

from persona_ai.personality.papua_live_system_instruction import (
    master_system_instruction_lines,
    master_system_instruction_text,
)


class TestPapuaLiveSystemInstruction:
    def test_master_lines_papua(self):
        lines = master_system_instruction_lines("papua", display_name="Papua AI")
        text = "\n".join(lines)
        assert "ROLE & IDENTITY" in text
        assert "RAJA MOP" in text
        assert "Sang Raja Mop" in text
        assert "MELAYU PAPUA" in text
        assert "MOP & HUMOR" in text
        assert "KNOWLEDGE BASE PRIORITIES" in text
        assert "Persipura" in text or "Boaz" in text
        assert "Adooo" in text or "Siooo" in text
        assert "tra lucu" in text.lower() or "belum dengar" in text.lower()

    def test_master_text_copy_paste(self):
        text = master_system_instruction_text("papua")
        assert "FULL-DUPLEX" in text
        assert "vokal panjang" in text.lower() or "Adooo paceee" in text

    def test_vowel_prosody_in_master(self):
        lines = master_system_instruction_lines("papua")
        text = "\n".join(lines).lower()
        assert "paceee" in text or "vokal" in text

    def test_skipped_non_papua(self):
        assert master_system_instruction_lines(None) == []
        assert master_system_instruction_text("jakarta") == ""
