"""Tests for Mop intro amunisi Raja Mop."""

from __future__ import annotations

from persona_ai.personality.papua_mop_intros import (
    emotional_tag_prompt_lines,
    mop_intro_prompt_lines,
    pick_mop_intro,
    punchline_pause_prompt_lines,
)
from persona_ai.personality.papua_mops import classic_mop_count, retrieve_mops


class TestMopIntros:
    def test_pick_intro(self):
        text = pick_mop_intro()
        assert len(text) > 20

    def test_intro_prompt_papua(self):
        lines = mop_intro_prompt_lines("papua")
        assert lines
        assert any("Menantang" in line for line in lines)

    def test_emotional_tags(self):
        lines = emotional_tag_prompt_lines("papua")
        assert any("Paling parah" in line for line in lines)

    def test_punchline_pause(self):
        lines = punchline_pause_prompt_lines("papua")
        assert any("..." in line for line in lines)

    def test_classic_mop_count_21(self):
        assert classic_mop_count() == 21

    def test_pick_horror_intro(self):
        text = pick_mop_intro(horror=True)
        assert len(text) > 20
        assert "setan" in text.lower() or "horor" in text.lower() or "kuburan" in text.lower()

    def test_retrieve_kipas_angin(self):
        hits = retrieve_mops("cerita mop kipas angin obet")
        assert hits
        assert any("kipas" in h.lower() or "helikopter" in h.lower() for h in hits)

    def test_retrieve_cendrawasih(self):
        hits = retrieve_mops("mop cendrawasih pns")
        assert hits
        assert any("cendrawasih" in h.lower() or "pns" in h.lower() for h in hits)
