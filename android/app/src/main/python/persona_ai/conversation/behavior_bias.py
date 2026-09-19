"""Light behavior tuning per conversation mode — never overrides safety/policy."""

from __future__ import annotations

from persona_ai.core.types import (
    BehaviorDirectiveVector,
    BehaviorInput,
    QuestionPolicy,
    ResponseLength,
    SpeakAction,
    ToneShift,
    VoiceDirective,
)
from persona_ai.conversation.scenarios import DEFAULT_SCENARIO_ID, get_scenario


def normalize_mode(mode: str | None) -> str:
    return (mode or DEFAULT_SCENARIO_ID).strip().lower() or DEFAULT_SCENARIO_ID


def bias_bdv_for_mode(
    bdv: BehaviorDirectiveVector,
    inp: BehaviorInput,
    *,
    conversation_mode: str | None,
) -> BehaviorDirectiveVector:
    mode = normalize_mode(conversation_mode)
    if mode == DEFAULT_SCENARIO_ID:
        return bdv

    intent = None
    from persona_ai.behavior.interpret import interpret

    intent = interpret(inp.message, inp.history.last_assistant_word_count)

    updates: dict[str, object] = {}

    if mode == "curhat":
        if intent.is_vent and bdv.speak == SpeakAction.RESPOND:
            updates = {
                "speak": SpeakAction.ACK_ONLY,
                "length": ResponseLength.MINIMAL,
                "partial_response": True,
                "engagement_level": 0.35,
                "tone_shift": ToneShift.WARMER,
                "question_budget": 0,
                "questions": QuestionPolicy.NONE,
            }
        elif bdv.speak == SpeakAction.RESPOND:
            updates = {
                "length": ResponseLength.MINIMAL,
                "partial_response": True,
                "question_budget": 0,
                "questions": QuestionPolicy.NONE,
            }

    elif mode == "funny" and bdv.speak == SpeakAction.RESPOND:
        updates = {
            "tone_shift": ToneShift.WARMER,
            "engagement_level": min(0.85, bdv.engagement_level + 0.12),
        }

    elif mode == "study" and bdv.speak == SpeakAction.RESPOND:
        updates = {
            "length": ResponseLength.NORMAL,
            "questions": QuestionPolicy.CLARIFY_ONLY,
            "question_budget": min(1, max(bdv.question_budget, 1)),
        }

    elif mode == "brainstorm" and bdv.speak == SpeakAction.RESPOND:
        updates = {
            "length": ResponseLength.NORMAL,
            "questions": QuestionPolicy.CLARIFY_ONLY,
            "question_budget": min(1, max(bdv.question_budget, 1)),
            "tone_shift": ToneShift.STABLE,
        }

    elif mode == "story" and bdv.speak == SpeakAction.RESPOND:
        updates = {
            "length": ResponseLength.EXPAND,
            "engagement_level": min(0.9, bdv.engagement_level + 0.1),
        }

    if not updates:
        return bdv
    return bdv.model_copy(update=updates)


def tune_voice_for_mode(
    voice: VoiceDirective,
    *,
    conversation_mode: str | None,
) -> VoiceDirective:
    mode = normalize_mode(conversation_mode)
    if mode == "curhat":
        return voice.model_copy(
            update={
                "max_words": min(voice.max_words, 28),
                "max_sentences": min(voice.max_sentences, 2),
                "question_budget": 0,
            }
        )
    if mode == "study":
        return voice.model_copy(
            update={
                "max_words": min(max(voice.max_words, 50), 90),
                "max_sentences": min(max(voice.max_sentences, 2), 4),
            }
        )
    if mode == "story":
        return voice.model_copy(
            update={
                "max_words": min(max(voice.max_words, 80), 140),
                "max_sentences": min(max(voice.max_sentences, 3), 6),
            }
        )
    _ = get_scenario(mode)
    return voice
