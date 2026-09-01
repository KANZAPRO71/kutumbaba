"""Tests for Mop landmark localization booster."""

from __future__ import annotations

from persona_ai.personality.papua_mop_landmarks import landmark_prompt_lines
from persona_ai.personality.papua_mops import mop_prompt_lines


class TestMopLandmarks:
    def test_landmark_prompt_jayapura(self):
        lines = landmark_prompt_lines("papua", query="cerita di jayapura youtefa")
        assert lines
        joined = " ".join(lines).lower()
        assert "youtefa" in joined or "abepura" in joined

    def test_landmark_prompt_sorong(self):
        lines = landmark_prompt_lines("papua", query="mop di sorong kilo")
        assert lines
        assert any("sorong" in line.lower() for line in lines)

    def test_landmark_in_mop_prompt(self):
        lines = mop_prompt_lines("papua", query="kasi mop di merauke")
        joined = " ".join(lines).lower()
        assert "merauke" in joined or "yobar" in joined or "ikon tempat" in joined
