"""Tests for Tabi — Port Numbay & Sentani marga module."""

from __future__ import annotations

from persona_ai.personality.papua_tabi import (
    detect_tabi_marga,
    marga_count,
    marga_response_hint,
    retrieve_tabi_facts,
    tabi_prompt_lines,
)


class TestPapuaTabi:
    def test_marga_count(self):
        assert marga_count() >= 40

    def test_detect_mano(self):
        assert detect_tabi_marga("Pace, sa dari marga Mano.") == "Mano"
        hint = marga_response_hint("Mano")
        assert "Mano" in hint
        assert "Tobati" in hint or "Youtefa" in hint

    def test_detect_wally_sentani(self):
        assert detect_tabi_marga("Sa marga Wally dari Sentani.") == "Wally"
        hint = marga_response_hint("Wally")
        assert "Wally" in hint
        assert "Ondoafi" in hint or "papeda" in hint.lower()

    def test_detect_kayobatu_marga(self):
        assert detect_tabi_marga("sa marga Makanuay") == "Makanuay"

    def test_no_false_positive_mari(self):
        assert detect_tabi_marga("mari su kitong pi spen") is None

    def test_retrieve_port_numbay(self):
        hits = retrieve_tabi_facts("port numbay tobati youtefa")
        assert hits
        text = " ".join(hits).lower()
        assert "numbay" in text or "tobati" in text or "youtefa" in text

    def test_retrieve_sentani_dusun_sagu(self):
        hits = retrieve_tabi_facts("sentani bhuvani dusun sagu yoboi")
        assert hits
        text = " ".join(hits).lower()
        assert "sentani" in text or "wally" in text or "bhuvani" in text

    def test_retrieve_taksi_sentani_phrase(self):
        hits = retrieve_tabi_facts("taksi sentani angkot jayapura")
        assert hits
        assert any("taksi sentani" in h.lower() for h in hits)

    def test_tabi_prompt_mano(self):
        lines = tabi_prompt_lines("papua", query="sa marga Mano tobati")
        joined = " ".join(lines)
        assert "Mano" in joined
        assert "Tabi" in joined or "Port Numbay" in joined
