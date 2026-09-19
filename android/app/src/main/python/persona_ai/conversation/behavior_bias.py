"""Light behavior tuning per experience / conversation mode — never overrides safety/policy."""

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
from persona_ai.conversation.experience_modes import (
    ExperienceModeProfile,
    get_experience_profile,
    normalize_experience_mode,
    scenario_id_for_mode,
)
from persona_ai.conversation.scenarios import DEFAULT_SCENARIO_ID, get_scenario


def normalize_mode(mode: str | None) -> str:
    return normalize_experience_mode(mode) if get_experience_profile(mode) else (
        (mode or DEFAULT_SCENARIO_ID).strip().lower() or DEFAULT_SCENARIO_ID
    )


def _apply_experience_behavior(
    bdv: BehaviorDirectiveVector,
    inp: BehaviorInput,
    profile: ExperienceModeProfile,
) -> BehaviorDirectiveVector:
    from persona_ai.behavior.interpret import interpret

    behavior = profile.behavior
    intent = interpret(inp.message, inp.history.last_assistant_word_count)
    updates: dict[str, object] = {}

    if profile.id == "cerita_tong" or profile.live.steer_profile == "curhat":
        if intent.is_vent and bdv.speak == SpeakAction.RESPOND:
            updates = {
                "speak": SpeakAction.ACK_ONLY,
                "length": ResponseLength.MINIMAL,
                "partial_response": True,
                "engagement_level": min(bdv.engagement_level, 0.35 + behavior.warmth_bias),
                "tone_shift": ToneShift.WARMER,
                "question_budget": 0,
                "questions": QuestionPolicy.NONE,
            }
        elif bdv.speak == SpeakAction.RESPOND:
            updates = {
                "length": ResponseLength.MINIMAL,
                "partial_response": True,
                "question_budget": min(behavior.question_budget, bdv.question_budget),
                "questions": QuestionPolicy.NONE if behavior.question_budget == 0 else bdv.questions,
            }
        if behavior.defer_bias >= 0.35 and intent.incompleteness_score >= 0.45:
            if bdv.speak == SpeakAction.RESPOND and not intent.is_direct_question:
                updates.setdefault("speak", SpeakAction.DEFER)

    elif profile.id == "mop" and bdv.speak == SpeakAction.RESPOND:
        updates = {
            "tone_shift": ToneShift.WARMER,
            "engagement_level": min(0.88, bdv.engagement_level + 0.14),
            "question_budget": 0,
            "questions": QuestionPolicy.NONE,
        }

    elif profile.id == "nongkrong" and bdv.speak == SpeakAction.RESPOND:
        updates = {
            "length": ResponseLength.MINIMAL if behavior.response_style == "short" else bdv.length,
            "question_budget": min(behavior.question_budget, max(bdv.question_budget, 1)),
        }

    elif profile.id == "teman_malam" and bdv.speak == SpeakAction.RESPOND:
        updates = {
            "length": ResponseLength.MINIMAL,
            "partial_response": True,
            "tone_shift": ToneShift.WARMER,
            "engagement_level": min(0.42, bdv.engagement_level),
            "question_budget": 0,
            "questions": QuestionPolicy.NONE,
        }

    elif profile.id == "teman_jalan":
        if bdv.speak == SpeakAction.RESPOND:
            if intent.is_direct_question or intent.requires_response:
                updates = {
                    "speak": SpeakAction.ACK_ONLY,
                    "length": ResponseLength.MINIMAL,
                    "partial_response": True,
                    "question_budget": 0,
                    "questions": QuestionPolicy.NONE,
                }
            else:
                updates = {
                    "length": ResponseLength.MINIMAL,
                    "partial_response": True,
                    "question_budget": 0,
                    "questions": QuestionPolicy.NONE,
                }
        elif behavior.ack_bias >= 0.5 and not intent.is_direct_question:
            updates = {"speak": SpeakAction.ACK_ONLY, "length": ResponseLength.MINIMAL}

    # Legacy scenario-only paths (settings / dev modes)
    mode_key = profile.scenario_id
    if not updates and mode_key == "study" and bdv.speak == SpeakAction.RESPOND:
        updates = {
            "length": ResponseLength.NORMAL,
            "questions": QuestionPolicy.CLARIFY_ONLY,
            "question_budget": min(1, max(bdv.question_budget, 1)),
        }
    elif not updates and mode_key == "brainstorm" and bdv.speak == SpeakAction.RESPOND:
        updates = {
            "length": ResponseLength.NORMAL,
            "questions": QuestionPolicy.CLARIFY_ONLY,
            "question_budget": min(1, max(bdv.question_budget, 1)),
            "tone_shift": ToneShift.STABLE,
        }
    elif not updates and mode_key == "story" and bdv.speak == SpeakAction.RESPOND:
        updates = {
            "length": ResponseLength.EXPAND,
            "engagement_level": min(0.9, bdv.engagement_level + 0.1),
        }

    if not updates:
        return bdv
    return bdv.model_copy(update=updates)


def bias_bdv_for_mode(
    bdv: BehaviorDirectiveVector,
    inp: BehaviorInput,
    *,
    conversation_mode: str | None,
) -> BehaviorDirectiveVector:
    profile = get_experience_profile(conversation_mode)
    if profile is not None:
        return _apply_experience_behavior(bdv, inp, profile)

    mode = (conversation_mode or DEFAULT_SCENARIO_ID).strip().lower() or DEFAULT_SCENARIO_ID
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
    profile = get_experience_profile(conversation_mode)
    if profile is not None:
        max_words = profile.live.max_response_words
        max_sentences = 2
        if profile.id == "teman_jalan":
            max_sentences = 1
        elif profile.id == "cerita_tong":
            max_sentences = 2
        elif profile.id == "mop":
            max_sentences = 3
        q_budget = profile.behavior.question_budget
        return voice.model_copy(
            update={
                "max_words": min(voice.max_words, max_words),
                "max_sentences": min(voice.max_sentences, max_sentences),
                "question_budget": min(voice.question_budget, q_budget),
            }
        )

    mode = (conversation_mode or DEFAULT_SCENARIO_ID).strip().lower() or DEFAULT_SCENARIO_ID
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
    _ = get_scenario(scenario_id_for_mode(mode))
    return voice
