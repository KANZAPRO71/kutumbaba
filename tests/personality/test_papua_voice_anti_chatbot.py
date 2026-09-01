"""Tests for voice anti-chatbot patterns."""

from __future__ import annotations

from persona_ai.personality.papua_voice_anti_chatbot import (
    natural_persona_refresh_text,
    natural_slip_nudge_text,
    score_voice_chatbot_slip,
    voice_not_chat_prompt_lines,
)
from persona_ai.personality.preset import load_default_preset
from persona_ai.web.voice_instruction import build_live_voice_instruction


def test_score_voice_chatbot_openers():
    score, hits = score_voice_chatbot_slip("Tentu saja! Saya dengar ko.")
    assert score > 0
    assert hits


def test_score_voice_chatbot_clean_reply():
    score, hits = score_voice_chatbot_slip("Adoo iyo toh — mantap cerita ko.")
    assert score == 0.0
    assert not hits


def test_score_voice_counselor_slip():
    score, hits = score_voice_chatbot_slip("Saya paham perasaan ko — wajar ko merasa begitu.")
    assert score > 0
    assert "VO17" in hits or "VO18" in hits or "VO19" in hits


def test_score_voice_article_slip():
    long_text = " ".join(["kata"] * 80)
    score, hits = score_voice_chatbot_slip(long_text)
    assert "VA1" in hits
    assert score > 0


def test_natural_persona_refresh_text():
    text = natural_persona_refresh_text(dialect="papua")
    assert "tongkrongan" in text
    assert "konselor" in text


def test_natural_slip_nudge_counselor():
    text = natural_slip_nudge_text(["VO17"], dialect="papua")
    assert "konselor" in text


def test_natural_slip_nudge_text():
    text = natural_slip_nudge_text(["VO1", "VO3"], dialect="papua")
    assert "Catatan internal" in text
    assert "Tentu saja" in text
    assert "PERSONA_GOVERNANCE" not in text


def test_instruction_compact_natural_anti_patterns():
    profile = load_default_preset()
    text = build_live_voice_instruction(profile, dialect="papua")
    assert len(text) < 3500
    assert "Tentu saja" in text
    assert "Saya dengar" in text
    assert "full duplex" in text.lower()
    assert voice_not_chat_prompt_lines("papua", language="id")[0].startswith("Suara")
