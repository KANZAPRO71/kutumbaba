"""Sprint B — Session Memory Card + listening telemetry."""

from __future__ import annotations

from persona_ai.conversation.behavior_bias import bias_bdv_for_mode, tune_voice_for_mode
from persona_ai.core.types import (
    BehaviorInput,
    Message,
    QuestionPolicy,
    ResponseLength,
    SpeakAction,
    ToneShift,
    VoiceDirective,
)
from persona_ai.behavior.engine import decide
from persona_ai.web.experience_turn_observer import _empty_session_stats, record_experience_turn
from persona_ai.web.session_memory_card import build_session_memory_card


def test_listening_ratio_user_dominates():
    gov = {
        "experience_session_stats": _empty_session_stats(),
        "conversation_mode": "cerita_tong",
        "last_governed_transcript": "Tadi sa ketemu teman lama dan cerita panjang.",
        "last_user_talk_ms": 260_000,
        "last_experience_bdv": "ACK_ONLY",
    }
    record_experience_turn(
        gov,
        runtime=None,
        session_id="s1",
        assistant_text="Hmm… terus?",
    )
    stats = gov["experience_session_stats"]
    assert stats["listening_ratio"] > 0.5
    assert stats["user_talk_duration_ms"] > stats["assistant_talk_duration_ms"]


def test_cerita_tong_low_questions_and_short_voice():
    msg = Message.from_text("user", "Tadi di kerja sa ada masalah besar…")
    inp = BehaviorInput(message=msg, conversation_mode="cerita_tong")
    bdv = decide(inp)
    bdv = bias_bdv_for_mode(bdv, inp, conversation_mode="cerita_tong")
    assert bdv.question_budget <= 1
    if bdv.speak == SpeakAction.RESPOND:
        assert bdv.length in {ResponseLength.MINIMAL, ResponseLength.NORMAL}
    voice = tune_voice_for_mode(
        VoiceDirective(
            speak=SpeakAction.RESPOND,
            effective_warmth=0.5,
            max_words=80,
            max_sentences=4,
            question_budget=2,
            tone_shift=ToneShift.STABLE,
        ),
        conversation_mode="cerita_tong",
    )
    assert voice.max_words <= 32
    assert voice.question_budget <= 1


def test_session_memory_card_human_sections():
    post_call = {
        "data": {
            "call_summary": "Ko cerita tentang teman lama hari ini.",
            "user_sentiment": "positive",
            "user_memories": [{"content": "Ko sedang mempertimbangkan beli motor."}],
            "open_loops": [{"topic": "motor", "content": "Belum tahu jadi beli atau tidak", "from_user": True}],
        },
        "experience_telemetry": {
            "listening_ratio": 0.8,
            "user_talk_duration_ms": 260_000,
            "assistant_talk_duration_ms": 65_000,
            "question_count": 1,
            "ack_only_count": 5,
        },
    }
    card = build_session_memory_card(
        session_id="abc",
        messages=[],
        post_call=post_call,
        experience_mode="cerita_tong",
    )
    assert card["sections"]["story"]
    assert card["sections"]["remember"]
    assert card["sections"]["unfinished"]
    assert card["listening_balance"]["percent"] == 80
    assert card["telemetry_summary"]["ack_only_count"] == 5
