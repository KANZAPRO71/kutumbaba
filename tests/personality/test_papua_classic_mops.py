"""Tests for classic Mop retrieval."""

from __future__ import annotations

from persona_ai.personality.papua_mops import (
    classic_mop_count,
    mop_count,
    pick_classic_mop,
    pick_random_mop,
    reset_random_mop_memory,
    retrieve_mops,
)


class TestClassicMops:
    def test_mop_count_includes_classics(self):
        assert mop_count() >= 265

    def test_pick_classic_mop(self):
        text = pick_classic_mop()
        assert text
        assert len(text) > 40

    def test_retrieve_kasi_mop(self):
        hits = retrieve_mops("Pace, kasi mop dulu kah!")
        assert hits
        joined = " ".join(hits).lower()
        assert "lampu merah" in joined or "gorden" in joined or "obet" in joined or "polisi" in joined

    def test_retrieve_mop_lampu_merah(self):
        hits = retrieve_mops("cerita mop lampu merah jayapura")
        assert hits
        assert any("lampu merah" in h.lower() for h in hits)

    def test_retrieve_mop_helm_terbalik(self):
        hits = retrieve_mops("cerita lucu helm terbalik merauke")
        assert hits
        assert any("helm" in h.lower() and "terbalik" in h.lower() for h in hits)

    def test_retrieve_mop_angkot(self):
        hits = retrieve_mops("kasi mop angkot jayapura")
        assert hits
        assert any("angkot" in h.lower() or "rumah" in h.lower() for h in hits)

    def test_classic_mop_count(self):
        assert classic_mop_count() == 21

    def test_retrieve_mop_tinus_jordan(self):
        hits = retrieve_mops("mop tinus sepatu jordan yombex anjing")
        assert hits
        assert any("tinus" in h.lower() or "jordan" in h.lower() or "yombex" in h.lower() for h in hits)

    def test_retrieve_mop_horor_setan(self):
        hits = retrieve_mops("kasi mop setan kuburan merauke yobar")
        assert hits
        assert any("kuntilanak" in h.lower() or "yobar" in h.lower() for h in hits)

    def test_retrieve_mop_pocong(self):
        hits = retrieve_mops("mop pocong angkot sorong")
        assert hits
        assert any("pocong" in h.lower() for h in hits)

    def test_pick_random_mop_varies(self):
        reset_random_mop_memory()
        first = pick_random_mop()
        second = pick_random_mop()
        assert len(first) > 40
        assert len(second) > 40

    def test_retrieve_mop_nokia(self):
        hits = retrieve_mops("cerita lucu hp nokia obet")
        assert hits
        assert any("nokia" in h.lower() or "panggilan" in h.lower() for h in hits)
