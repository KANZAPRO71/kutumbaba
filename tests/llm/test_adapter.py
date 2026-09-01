"""LLM adapter v0.4 tests — thin wire, no behavior leakage."""

from persona_ai.conversation.pipeline_v0 import process_turn
from persona_ai.core.types import LLMRequest, ResponseLength, SpeakAction, ToneShift, TurnHistory, VoiceDirective
from persona_ai.llm.adapter import render, score_cps
from persona_ai.llm.prompt import build_system_prompt
from tests.support.stub_llm import StubLLMAdapter


def _voice(**kwargs) -> VoiceDirective:
    defaults = dict(
        speak=SpeakAction.RESPOND,
        effective_warmth=0.6,
        max_words=30,
        max_sentences=2,
        question_budget=0,
        tone_shift=ToneShift.STABLE,
        prompt_fragments=["Do not ask closing offers."],
    )
    defaults.update(kwargs)
    return VoiceDirective(**defaults)


class TestRender:
    def test_silence_returns_none(self):
        assert render(_voice(speak=SpeakAction.SILENCE), "hello") is None

    def test_ack_does_not_use_canned_template(self):
        v = _voice(speak=SpeakAction.ACK_ONLY, template_ack="Berat ya.")
        text = render(v, "capek", StubLLMAdapter())
        assert text != "Berat ya."

    def test_respond_via_stub(self):
        text = render(_voice(), "besok meeting jam berapa?", StubLLMAdapter())
        assert text and len(text.split()) <= 30


class TestPromptPurity:
    def test_no_internal_layer_leakage(self):
        prompt = build_system_prompt(LLMRequest(user_message="hi", voice=_voice()))
        assert "Max words" in prompt
        assert "arbitration" not in prompt.lower()
        assert "cqf" not in prompt.lower()

    def test_zero_budget_forbids_engagement_questions(self):
        prompt = build_system_prompt(LLMRequest(user_message="hi", voice=_voice()))
        assert "Questions you may ask: 0" in prompt
        assert "ZERO questions" in prompt
        assert "ada yang mau ditanyakan" in prompt


class TestStripTrailingQuestions:
    def test_keeps_the_answer(self):
        from persona_ai.llm.prompt import strip_trailing_questions

        text = strip_trailing_questions(
            "Besok jam 9 di kantor. Ada yang mau kamu tanyakan lagi?"
        )
        assert "Besok jam 9" in text
        assert "tanyakan" not in text.lower()

    def test_drops_lone_closer(self):
        from persona_ai.llm.prompt import strip_trailing_questions

        assert strip_trailing_questions("Ada yang mau ditanyakan?") == ""


class TestCPS:
    def test_detects_chatbot_phrase(self):
        score, hits = score_cps("Ada lagi yang bisa saya bantu?")
        assert score >= 0.8 and "CP1" in hits

    def test_detects_followup_closer(self):
        score, hits = score_cps("Ada yang mau kamu tanyakan lagi?")
        assert score >= 0.8 and "CP3" in hits


class TestPipelineE2E:
    def test_vent_whisper_uses_llm_not_canned_ack(self):
        out = process_turn("s1", "Ah capek banget hari ini ya...")
        assert out.text not in ("Berat ya.", "Iyaa, paham.", "Iya.")
        assert out.text

    def test_question_gets_text(self):
        out = process_turn("s2", "Besok meeting jam berapa?")
        assert out.text
        assert out.voice.speak == SpeakAction.RESPOND

    def test_closure_silent(self):
        hist = TurnHistory(last_assistant_word_count=200, last_assistant_verbosity=ResponseLength.EXPAND)
        out = process_turn("s3", "Oke", history=hist)
        assert out.text is None
