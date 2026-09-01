"""Tests for Biak Wós Vyak, Ararem, and lagu module."""

from __future__ import annotations

from persona_ai.personality.papua_biak import (
    biak_prompt_lines,
    retrieve_biak_facts,
    vocabulary_count,
)
from persona_ai.personality.papua_knowledge import retrieve_knowledge_facts
from persona_ai.personality.papua_music import retrieve_music_facts


class TestPapuaBiak:
    def test_vocabulary_count(self):
        assert vocabulary_count() >= 14

    def test_keret_count(self):
        from persona_ai.personality.papua_biak import keret_count

        assert keret_count() >= 20

    def test_detect_keret_rumbiak(self):
        from persona_ai.personality.papua_biak import detect_keret, keret_response_hint

        assert detect_keret("Pace, sa punya nama Yohanis Rumbiak.") == "Rumbiak"
        hint = keret_response_hint("Rumbiak")
        assert "Rumbiak" in hint
        assert "Syowi" in hint

    def test_detect_keret_auwr(self):
        from persona_ai.personality.papua_biak import detect_keret

        assert detect_keret("sa dari keret Fairyo") == "Fairyo"

    def test_retrieve_wor_ersam(self):
        hits = retrieve_biak_facts("wor ersam korfandi berlayar biak")
        assert hits
        text = " ".join(hits).lower()
        assert "ersam" in text or "wor" in text or "samudra" in text

    def test_retrieve_sub_suku(self):
        hits = retrieve_biak_facts("sub suku biak aimando doreri")
        assert hits
        assert any("aimando" in h.lower() or "doreri" in h.lower() for h in hits)

    def test_retrieve_kabor(self):
        hits = retrieve_biak_facts("kabor akur mambri pesisir biak")
        assert hits
        text = " ".join(hits).lower()
        assert "kabor" in text or "akur" in text or "mambri" in text

    def test_ararem_dialog_uang_susu(self):
        hits = retrieve_biak_facts("mas kawin orang biak apa saja ararem")
        assert hits
        text = " ".join(hits).lower()
        assert "benjaf" in text or "sner" in text or "uang susu" in text or "kain gendong" in text

        hits = retrieve_biak_facts("ararem piring gantung benjaf sner")
        assert hits
        text = " ".join(hits).lower()
        assert "piring" in text or "benjaf" in text or "sner" in text

    def test_retrieve_syowi(self):
        hits = retrieve_biak_facts("syowi kopyum bahasa biak")
        assert hits
        text = " ".join(hits).lower()
        assert "syowi" in text or "kopyum" in text or "wós vyak" in text

    def test_retrieve_lagu_wondama(self):
        hits = retrieve_biak_facts("lagu wondama biak")
        assert hits
        assert any("wondama" in h.lower() for h in hits)

    def test_biak_prompt_overview(self):
        lines = biak_prompt_lines("papua", include_overview=True)
        assert lines
        joined = " ".join(lines).lower()
        assert "wós vyak" in joined or "biak" in joined
        assert "syowi" in joined or "ararem" in joined

    def test_detect_keret_no_false_mari(self):
        from persona_ai.personality.papua_biak import detect_keret

        assert detect_keret("mari su kitong ngobrol") is None

    def test_biak_prompt_keret(self):
        lines = biak_prompt_lines("papua", query="Yohanis Rumbiak dari Biak")
        joined = " ".join(lines)
        assert "Rumbiak" in joined

    def test_knowledge_farkawawin(self):
        facts = retrieve_knowledge_facts("farkawawin mas kawin biak wor")
        assert facts
        text = " ".join(facts).lower()
        assert "ararem" in text or "farkawawin" in text or "wor" in text

    def test_music_diru_diru(self):
        facts = retrieve_music_facts("diru diru nina lagu biak")
        assert facts
        assert any("diru" in f.lower() or "biak" in f.lower() for f in facts)
