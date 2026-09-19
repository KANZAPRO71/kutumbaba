"""Experience Mode profiles — BDV bias + callback gate."""

from __future__ import annotations

from persona_ai.conversation.behavior_bias import bias_bdv_for_mode, tune_voice_for_mode
from persona_ai.conversation.experience_modes import (
    get_experience_profile,
    normalize_experience_mode,
    should_callback,
)
from persona_ai.core.types import (
    BehaviorInput,
    Message,
    SpeakAction,
    ToneShift,
    VoiceDirective,
)
from persona_ai.behavior.engine import decide


def test_legacy_aliases_normalize():
    assert normalize_experience_mode("casual_chat") == "nongkrong"
    assert normalize_experience_mode("curhat") == "cerita_tong"
    assert normalize_experience_mode("funny") == "mop"


def test_cerita_tong_limits_voice():
    voice = VoiceDirective(
        speak=SpeakAction.RESPOND,
        effective_warmth=0.5,
        max_words=80,
        max_sentences=4,
        question_budget=2,
        tone_shift=ToneShift.STABLE,
    )
    tuned = tune_voice_for_mode(voice, conversation_mode="cerita_tong")
    assert tuned.max_words <= 32
    assert tuned.question_budget <= 1


def test_teman_jalan_ultra_short():
    profile = get_experience_profile("teman_jalan")
    assert profile is not None
    assert profile.live.max_response_words <= 20
    voice = tune_voice_for_mode(
        VoiceDirective(
            speak=SpeakAction.RESPOND,
            effective_warmth=0.5,
            max_words=90,
            max_sentences=4,
            question_budget=2,
            tone_shift=ToneShift.STABLE,
        ),
        conversation_mode="teman_jalan",
    )
    assert voice.max_words <= 18
    assert voice.max_sentences <= 1


def test_cerita_tong_vent_ack():
    msg = Message.from_text("user", "Ah capek banget hari ini ya...")
    inp = BehaviorInput(message=msg, conversation_mode="cerita_tong")
    bdv = decide(inp)
    bdv = bias_bdv_for_mode(bdv, inp, conversation_mode="cerita_tong")
    assert bdv.speak in {SpeakAction.ACK_ONLY, SpeakAction.RESPOND, SpeakAction.DEFER}
    assert bdv.question_budget == 0 or bdv.speak != SpeakAction.RESPOND


def test_callback_gate_respects_mode_and_quota():
    assert not should_callback(
        mode="teman_jalan",
        loop_priority=0.9,
        mentioned_today=False,
        callbacks_used_today=0,
    )
    assert should_callback(
        mode="nongkrong",
        loop_priority=0.5,
        mentioned_today=False,
        callbacks_used_today=0,
    )
    assert not should_callback(
        mode="nongkrong",
        loop_priority=0.5,
        mentioned_today=True,
        callbacks_used_today=0,
    )
    assert not should_callback(
        mode="nongkrong",
        loop_priority=0.5,
        mentioned_today=False,
        callbacks_used_today=1,
    )
