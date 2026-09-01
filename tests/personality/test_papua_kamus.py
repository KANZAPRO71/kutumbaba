"""Tests for Papua kamus (dictionary)."""

from __future__ import annotations

from persona_ai.personality.papua_kamus import (
    entry_count,
    kamus_prompt_lines,
    lookup_word,
    preview_entries,
    retrieve_kamus,
)


class TestPapuaKamus:
    def test_catalog_substantial(self):
        assert entry_count() >= 350

    def test_lookup_tra(self):
        hit = lookup_word("tra")
        assert hit is not None
        assert "tidak" in str(hit.get("meaning", "")).lower()

    def test_lookup_mangarti(self):
        hit = lookup_word("mangarti")
        assert hit is not None
        assert "mengerti" in str(hit.get("meaning", "")).lower()

    def test_lookup_variant(self):
        hit = lookup_word("Adoh")
        assert hit is not None
        assert "aduh" in str(hit.get("meaning", "")).lower()

    def test_retrieve_word_in_query(self):
        hits = retrieve_kamus("Ko tau arti mangarti?")
        assert hits
        assert any("mangarti" in h.lower() for h in hits)

    def test_retrieve_kamus_keyword(self):
        hits = retrieve_kamus("Ada di kamus bahasa Papua kata bale?")
        assert hits
        assert any("bale" in h.lower() or "balik" in h.lower() for h in hits)

    def test_kamus_prompt_papua(self):
        lines = kamus_prompt_lines("papua", include_overview=True)
        assert any("Kamus Bahasa Papua" in line for line in lines)
        assert any("366" in line or str(entry_count()) in line for line in lines)

    def test_kamus_prompt_with_query(self):
        lines = kamus_prompt_lines("papua", query="arti kata mamayo", include_overview=False)
        text = "\n".join(lines).lower()
        assert "mamayo" in text or "relevan" in text

    def test_kamus_prompt_skipped_non_papua(self):
        assert kamus_prompt_lines(None) == []
        assert kamus_prompt_lines("jakarta") == []

    def test_preview_entries(self):
        previews = preview_entries(5)
        assert len(previews) == 5
        assert all("=" in p for p in previews)
