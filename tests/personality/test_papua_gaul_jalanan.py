"""Tests for Jayapura street slang — Yombex, pamer detection."""

from __future__ import annotations

from persona_ai.personality.papua_gaul_jalanan import (
    detect_baku_tangkis,
    detect_pamer,
    gaul_jalanan_prompt_lines,
    gaul_word_count,
    retrieve_gaul_facts,
    yombex_pamer_response,
)
from persona_ai.personality.papua_dialect_phrases import slang_barge_in_responses


class TestPapuaGaulJalanan:
    def test_word_count(self):
        assert gaul_word_count() >= 5

    def test_detect_pamer_hp(self):
        assert detect_pamer("sa baru beli HP Android paling mahal")

    def test_yombex_response_hp(self):
        resp = yombex_pamer_response("AI, sa baru beli HP Android paling mahal")
        assert resp
        assert "yombex" in resp.lower()
        assert "HP" in resp or "hp" in resp.lower()

    def test_retrieve_yombex_meaning(self):
        hits = retrieve_gaul_facts("apa arti yombex jayapura")
        assert hits
        assert any("yombex" in h.lower() for h in hits)

    def test_retrieve_kalkota_kombas(self):
        hits = retrieve_gaul_facts("kalkota kombas sakar gaul")
        text = " ".join(hits).lower()
        assert "kalkota" in text or "kombas" in text or "sakar" in text

    def test_gaul_prompt_pamer(self):
        lines = gaul_jalanan_prompt_lines(
            "papua",
            query="sa baru beli hp mahal kodingan lancar",
        )
        joined = " ".join(lines).lower()
        assert "yombex" in joined
        assert "pamer" in joined or "terdeteksi" in joined

    def test_slang_barge_in_includes_yombex(self):
        items = slang_barge_in_responses()
        assert any(
            "yombex" in str(item.get("response", "")).lower()
            for item in items
            if isinstance(item, dict)
        )

    def test_no_pamer_false_positive(self):
        assert not detect_pamer("mari su kitong ngobrol santai")

    def test_baku_tangkis_akur_spen(self):
        resp = detect_baku_tangkis("Pace AI, kitong pi spen di jembatan merah kah?")
        assert resp
        assert "akur" in resp.lower()
        assert "bensin" in resp.lower()

    def test_baku_tangkis_kalkota_artis(self):
        resp = detect_baku_tangkis("AI, sa kemarin jalan dengan artis")
        assert resp
        assert "kalkota" in resp.lower()
        assert "yombex" in resp.lower()

    def test_gaul_prompt_baku_tangkis_mode(self):
        lines = gaul_jalanan_prompt_lines("papua")
        joined = " ".join(lines).lower()
        assert "baku tangkis" in joined or "slengean" in joined
