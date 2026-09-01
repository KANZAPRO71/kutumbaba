"""Tests for Live voice instruction builder."""

from __future__ import annotations

from persona_ai.core.types import Message, SpeakAction, ToneShift, VoiceDirective
from persona_ai.personality.preset import load_default_preset
from persona_ai.web.voice_instruction import (
    build_live_engine_instruction,
    build_live_voice_instruction,
    format_live_history_block,
    pending_user_utterance,
)


class TestVoiceInstruction:
    def test_baseline_from_preset(self):
        profile = load_default_preset()
        text = build_live_voice_instruction(profile)
        assert "Bahasa Indonesia" in text
        assert "ChatGPT voice" not in text
        assert "teman ngobrol" in text.lower() or "friend" in text.lower()
        assert "Current Time Awareness:" in text
        assert "PERSONA_GOVERNANCE" not in text
        assert "Agent Handbook" not in text
        assert "Turn protocol" not in text
        assert len(text) < 3500
        assert "Anti-ulang" not in text
        assert "Anti-chatbot" not in text
        assert "Suara & prosody" not in text

    def test_instruction_includes_prior_conversation(self):
        profile = load_default_preset()
        history = [
            Message.from_text("user", "Gimana masa depan AI?"),
            Message.from_text("assistant", "Aku kira asistennya makin bisa ngerjain tugas nyata."),
            Message.from_text("user", "Coba kamu cari dulu kenapa masalahnya."),
        ]
        text = build_live_voice_instruction(profile, history=history)
        assert "Gimana masa depan AI?" in text
        assert "Percakapan terbaru" in text or "CONVERSATION MEMORY" in text
        assert "call reconnected" not in text

    def test_history_block_collapses_growing_partials(self):
        history = [
            Message.from_text("user", "Kalau saya sih lebih pengen AI itu bisa order Grab"),
            Message.from_text("user", "Kalau saya sih lebih pengen AI itu bisa order Grab, Gojek"),
        ]
        block = format_live_history_block(history)
        assert block.count("Ko:") == 1
        assert "Gojek" in block

    def test_pending_user_utterance_is_unanswered_last_line(self):
        history = [
            Message.from_text("user", "ada mobil Honda di tahunnya M. M itu apa?"),
        ]
        assert pending_user_utterance(history) == "ada mobil Honda di tahunnya M. M itu apa?"
        history.append(Message.from_text("assistant", "M itu kode tahun Honda."))
        assert pending_user_utterance(history) is None

    def test_engine_instruction_includes_conversation_thread(self):
        profile = load_default_preset()
        voice = VoiceDirective(
            speak=SpeakAction.RESPOND,
            effective_warmth=0.7,
            max_words=40,
            max_sentences=2,
            question_budget=0,
            tone_shift=ToneShift.STABLE,
            prompt_fragments=["Speak like a friend."],
        )
        history = [
            Message.from_text("user", "ada mobil Honda di tahunnya M. M itu apa?"),
        ]
        text = build_live_engine_instruction(profile, voice, history=history)
        assert "ada mobil Honda" in text
        assert "Percakapan terbaru" in text or "CONVERSATION MEMORY" in text

    def test_papua_dialect_overlay(self):
        profile = load_default_preset()
        text = build_live_voice_instruction(profile, dialect="papua")
        assert "Papua" in text
        assert "sobat jayapura" in text.lower()
        assert " sa/ko" in text.lower() or "sa/ko" in text.lower()
        assert len(text) < 3500
        assert "Pengetahuan Papua" not in text
        assert build_live_voice_instruction(profile, dialect=None) != text

    def test_papua_phrase_corpus_size(self):
        from persona_ai.personality.papua_dialect_phrases import phrase_count

        assert phrase_count() >= 130

    def test_engine_instruction_includes_voice_directive(self):
        profile = load_default_preset()
        voice = VoiceDirective(
            speak=SpeakAction.RESPOND,
            effective_warmth=0.7,
            max_words=40,
            max_sentences=2,
            question_budget=0,
            tone_shift=ToneShift.STABLE,
            prompt_fragments=["Speak like a friend."],
        )
        text = build_live_engine_instruction(profile, voice)
        assert "Max words: 40" in text
        assert "Speak like a friend." in text
