"""Tests for Papua music catalog."""

from __future__ import annotations

from persona_ai.personality.papua_music import (
    catalog_count,
    music_prompt_lines,
    preview_songs,
    retrieve_music_facts,
    song_count,
)


class TestPapuaMusic:
    def test_catalog_substantial(self):
        assert song_count() >= 25
        assert catalog_count() >= 30

    def test_retrieve_apuse(self):
        hits = retrieve_music_facts("Ko tau lagu Apuse?")
        assert hits
        assert any("apuse" in h.lower() for h in hits)

    def test_retrieve_franky(self):
        hits = retrieve_music_facts("Franky Sahilatua artis Papua")
        assert hits
        text = " ".join(hits).lower()
        assert "franky" in text or "abe" in text or "apuse" in text

    def test_retrieve_yospan(self):
        hits = retrieve_music_facts("musik yospan tarian remaja")
        assert hits
        assert any("yospan" in h.lower() for h in hits)

    def test_retrieve_gospel(self):
        hits = retrieve_music_facts("lagu gospel gereja papua")
        assert hits

    def test_music_prompt_papua(self):
        lines = music_prompt_lines("papua", include_overview=True)
        assert any("Katalog musik" in line for line in lines)
        assert any("Apuse" in line for line in lines)

    def test_music_prompt_with_query(self):
        lines = music_prompt_lines("papua", query="lagu Yamko Rambe Yamko", include_overview=False)
        text = "\n".join(lines).lower()
        assert "yamko" in text or "relevan" in text

    def test_music_prompt_skipped_non_papua(self):
        assert music_prompt_lines(None) == []
        assert music_prompt_lines("jakarta") == []

    def test_preview_songs(self):
        previews = preview_songs(5)
        assert len(previews) == 5

    def test_retrieve_jang_ganggu(self):
        hits = retrieve_music_facts("lagu Jang Ganggu Shine of Black angkot")
        assert hits
        text = " ".join(hits).lower()
        assert "jang ganggu" in text or "shine" in text

    def test_retrieve_mac_cuma_saya(self):
        hits = retrieve_music_facts("MAC Cuma Saya hip hop Papua")
        assert hits
        text = " ".join(hits).lower()
        assert "cuma saya" in text or "mac" in text or "m.a.c" in text

    def test_retrieve_whllyano(self):
        hits = retrieve_music_facts("Whllyano Ko Menang Banyak nongkrong")
        assert hits
        text = " ".join(hits).lower()
        assert "whllyano" in text or "menang banyak" in text

    def test_retrieve_yance_tanah_papua(self):
        hits = retrieve_music_facts("Yance Rumbino Tanah Papua nyanyi")
        assert hits
        text = " ".join(hits).lower()
        assert "yance" in text or "tanah papua" in text
