"""Tests for Ondoafi wibawa module."""

from __future__ import annotations

from persona_ai.personality.papua_ondo_wibawa import ondo_wibawa_prompt_lines


class TestOndoWibawa:
    def test_prompt_overview(self):
        lines = ondo_wibawa_prompt_lines("papua")
        joined = " ".join(lines).lower()
        assert "ondoafi" in joined or "khano" in joined
        assert "amolongo" in joined or "afoooo" in joined

    def test_prompt_query(self):
        lines = ondo_wibawa_prompt_lines("papua", query="cerita ondoafi rapat ulayat")
        joined = " ".join(lines).lower()
        assert "obhe" in joined or "ulayat" in joined or "ondoafi" in joined
