"""Tests for Papua Mop collection."""

from __future__ import annotations

from persona_ai.personality.papua_mops import (
    mop_count,
    mop_prompt_lines,
    preview_mops,
    retrieve_mops,
    session_mop_samples,
)


class TestPapuaMops:
    def test_mop_count_substantial(self):
        assert mop_count() >= 200

    def test_session_samples(self):
        samples = session_mop_samples()
        assert len(samples) >= 4
        assert any("mamayo" in s.lower() or "eee" in s.lower() for s in samples)

    def test_preview_mops(self):
        previews = preview_mops(4)
        assert len(previews) == 4
        assert all(isinstance(p, str) and p.strip() for p in previews)

    def test_retrieve_humor_query(self):
        hits = retrieve_mops("Ko ada cerita lucu mop kah?")
        assert hits

    def test_retrieve_mamayo(self):
        hits = retrieve_mops("mamayo gol bola")
        assert hits
        assert any("mamayo" in h.lower() or "bola" in h.lower() for h in hits)

    def test_mop_prompt_papua_dialect(self):
        lines = mop_prompt_lines("papua", include_session_samples=True)
        assert any("Koleksi Mop Papua" in line for line in lines)
        assert any("Mop" in line for line in lines)

    def test_mop_prompt_skipped_non_papua(self):
        assert mop_prompt_lines(None) == []
        assert mop_prompt_lines("jakarta") == []

    def test_mop_offer_phrases(self):
        from persona_ai.personality.papua_mops import mop_offer_phrases, mop_offer_prompt_lines

        phrases = mop_offer_phrases()
        assert any("mo dengar" in p.lower() for p in phrases)
        offer_lines = mop_offer_prompt_lines()
        assert any("Penawaran Mop" in line for line in offer_lines)
        assert any("Ko mo dengar" in line for line in offer_lines)

    def test_mop_prompt_includes_offer(self):
        lines = mop_prompt_lines("papua", include_session_samples=False)
        text = "\n".join(lines)
        assert "Penawaran Mop" in text

    def test_mop_prompt_with_query(self):
        lines = mop_prompt_lines("papua", query="cerita lucu epen cupen", include_session_samples=False)
        text = "\n".join(lines).lower()
        assert "mop" in text or "epen" in text or "relevan" in text
