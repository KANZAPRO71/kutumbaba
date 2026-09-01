"""Tests for Papua dialect companion persona."""

from __future__ import annotations

from persona_ai.personality.papua_dialect_phrases import (
    ack_templates_papua,
    companion_persona_prompt_lines,
    dialect_prompt_lines,
    full_duplex_prompt_lines,
    papua_friend_lines,
    papua_opening_greeting_prompt,
)


class TestPapuaCompanionPersona:
    def test_friend_lines_sobat_jayapura(self):
        lines = papua_friend_lines()
        text = "\n".join(lines).lower()
        assert "sobat" in text
        assert "jayapura" in text
        assert "mop" in text
        assert "siooo" in text or "full duplex" in text

    def test_companion_persona_prompt(self):
        lines = companion_persona_prompt_lines()
        assert lines
        text = "\n".join(lines).lower()
        assert "nongkrong" in text
        assert "papeda" in text

    def test_full_duplex_prompt(self):
        lines = full_duplex_prompt_lines()
        assert any("full duplex" in line.lower() for line in lines)
        assert any("siooo" in line.lower() for line in lines)

    def test_slang_barge_in_templates(self):
        from persona_ai.personality.papua_dialect_phrases import slang_barge_in_prompt_lines

        lines = slang_barge_in_prompt_lines()
        text = "\n".join(lines).lower()
        assert "ko tipu" in text
        assert "iyo toh" in text
        assert "sentani" in text or "kasihan" in text

    def test_opening_greeting_warm(self):
        prompt = papua_opening_greeting_prompt("Papua AI")
        assert "beberapa kalimat" in prompt.lower() or "panjang" in prompt.lower()
        assert "papeda" in prompt.lower()
        assert "adooo" in prompt.lower() or "tra tidur" in prompt.lower()
        assert "beta" in prompt.lower()

    def test_opening_canonical(self):
        from persona_ai.personality.papua_dialect_phrases import opening_greeting_canonical

        canonical = opening_greeting_canonical()
        assert "adooo pace" in canonical.lower()
        assert "papeda" in canonical.lower()
        assert "tra tidur" in canonical.lower()

    def test_ack_humor_and_interruption(self):
        acks = ack_templates_papua()
        assert acks.get("humor")
        assert acks.get("interruption")
        assert any("hahaha" in p.lower() for p in acks["humor"])
        assert any("siooo" in p.lower() for p in acks["interruption"])

    def test_dialect_prompt_includes_persona(self):
        lines = dialect_prompt_lines("papua")
        text = "\n".join(lines).lower()
        assert "sobat" in text
        assert "full duplex" in text
