"""Tests for Papua voice prosody & emotional audio."""

from __future__ import annotations

from persona_ai.personality.papua_voice_prosody import (
    emotional_audio_prompt_lines,
    voice_prosody_prompt_lines,
)


class TestPapuaVoiceProsody:
    def test_prosody_particles(self):
        lines = voice_prosody_prompt_lines("papua")
        text = "\n".join(lines).lower()
        assert "toh" in text
        assert "kah" in text
        assert "prosody" in text or "ayunan" in text

    def test_emotional_laughter(self):
        lines = emotional_audio_prompt_lines("papua")
        text = "\n".join(lines).lower()
        assert "tawa" in text or "ketawa" in text or "hehe" in text
        assert "tra kedengaran dibuat-buat" in text or "natural" in text

    def test_skipped_non_papua(self):
        assert voice_prosody_prompt_lines(None) == []
        assert emotional_audio_prompt_lines("jakarta") == []
