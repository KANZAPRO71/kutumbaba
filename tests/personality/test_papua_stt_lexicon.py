"""Tests for Papua STT lexicon tuning."""

from __future__ import annotations

from persona_ai.personality.papua_stt_lexicon import (
    boosted_keywords,
    contextual_mappings,
    enrich_voice_config_for_papua,
    normalize_papua_transcript,
    phonetic_entries,
    slang_aliases,
    stt_prompt_lines,
)
from persona_ai.web.voice_config import LiveVoiceConfig


class TestPapuaSttLexicon:
    def test_boosted_keywords_substantial(self):
        kw = boosted_keywords()
        assert len(kw) >= 30
        assert "tra" in kw
        assert "paitua" in kw
        assert "persipura" in kw

    def test_phonetic_tra_not_tren(self):
        entries = {e["word"]: e for e in phonetic_entries()}
        assert "tra" in entries
        avoid = entries["tra"].get("avoid_as") or []
        assert any("tren" in str(a).lower() for a in avoid)

    def test_slang_aliases(self):
        aliases = slang_aliases()
        assert any(a.get("alias") == "drg" for a in aliases)
        assert any(a.get("word") == "kam" for a in aliases)

    def test_stt_prompt_papua(self):
        lines = stt_prompt_lines("papua")
        text = "\n".join(lines).lower()
        assert "tra" in text
        assert "tren" in text or "truk" in text
        assert "drg" in text or "dorang" in text

    def test_enrich_voice_config(self):
        base = LiveVoiceConfig(boosted_keywords=("Papua",))
        enriched = enrich_voice_config_for_papua(base)
        assert len(enriched.boosted_keywords) > len(base.boosted_keywords)
        assert enriched.pronunciations

    def test_stt_skipped_non_papua(self):
        assert stt_prompt_lines(None) == []
        assert stt_prompt_lines("jakarta") == []

    def test_normalize_tra_from_tren(self):
        assert normalize_papua_transcript("sa tren mo pi") == "sa tra mo pi"

    def test_normalize_kitong_from_kintong(self):
        assert normalize_papua_transcript("kintong mo pi") == "kitong mo pi"

    def test_normalize_baku_dapa(self):
        assert normalize_papua_transcript("kitong baku dapat") == "kitong baku dapa"

    def test_normalize_skipped_non_papua(self):
        assert normalize_papua_transcript("sa tren mo pi", dialect=None) == "sa tren mo pi"

    def test_contextual_mappings_loaded(self):
        assert len(contextual_mappings()) >= 10
