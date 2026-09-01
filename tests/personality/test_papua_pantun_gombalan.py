"""Tests for pantun & gombalan Timur module."""

from __future__ import annotations

from persona_ai.personality.papua_pantun_gombalan import (
    gombalan_count,
    pantun_gombalan_prompt_lines,
    retrieve_gombalan,
)


class TestPantunGombalan:
    def test_gombalan_count(self):
        assert gombalan_count() >= 3

    def test_retrieve_gombal_noken(self):
        hits = retrieve_gombalan("kasih gombal pake noken maitua")
        assert hits
        assert any("noken" in h.lower() for h in hits)

    def test_retrieve_gombal_abepura(self):
        hits = retrieve_gombalan("gombal komedi abepura macet")
        assert hits
        assert any("abepura" in h.lower() or "macet" in h.lower() for h in hits)

    def test_prompt_overview(self):
        lines = pantun_gombalan_prompt_lines("papua")
        joined = " ".join(lines).lower()
        assert "gombal" in joined or "pantun" in joined

    def test_prompt_query(self):
        lines = pantun_gombalan_prompt_lines("papua", query="ajari gombal sunset kaimana")
        joined = " ".join(lines).lower()
        assert "kaimana" in joined or "sunset" in joined or "gombal" in joined
