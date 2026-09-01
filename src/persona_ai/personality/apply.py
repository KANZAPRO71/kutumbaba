"""Personality — v0.2 light expression."""

from __future__ import annotations

from persona_ai.core.types import (
    BehaviorDirectiveVector,
    ConversationArc,
    ExpressionConstraints,
    PersonalityProfile,
    ResponseLength,
    SpeakAction,
    ToneShift,
    clamp,
)

_LANGUAGE_PROMPTS = {
    "id": "Always respond in Bahasa Indonesia — natural, conversational, not formal or translated-sounding.",
    "en": "Always respond in English — natural and conversational.",
}


def _language_prompt(profile: PersonalityProfile) -> str:
    return _LANGUAGE_PROMPTS.get(profile.default_language, _LANGUAGE_PROMPTS["id"])


def apply(
    profile: PersonalityProfile,
    bdv: BehaviorDirectiveVector,
    arc: ConversationArc | None = None,
    execution_profile: str = "standard",
) -> ExpressionConstraints:
    del execution_profile
    shift_delta = {
        ToneShift.STABLE: 0.0,
        ToneShift.WARMER: 0.12,
        ToneShift.SOFTER: 0.08,
        ToneShift.MATCH_USER: 0.05,
    }[bdv.tone_shift]

    arc_warmth = arc.relational_warmth * 0.1 if arc else 0.0
    effective_warmth = clamp(profile.warmth + shift_delta + arc_warmth)

    max_words = {
        ResponseLength.MINIMAL: profile.max_words_minimal,
        ResponseLength.NORMAL: profile.max_words_normal,
        ResponseLength.EXPAND: profile.max_words_expand,
    }[bdv.length]
    max_sentences = {ResponseLength.MINIMAL: 1, ResponseLength.NORMAL: 3, ResponseLength.EXPAND: 6}[bdv.length]
    if bdv.partial_response:
        max_sentences = 1
        max_words = min(max_words, 18)

    register = "warm" if effective_warmth > 0.65 else ("casual" if profile.formality < 0.5 else "neutral")

    fragments = [
        _language_prompt(profile),
        "Write like a capable friend hanging out: relaxed, clear, genuinely useful — not an interviewer.",
        (
            "Do not ask any question. Do not end with a question mark. "
            "Jangan tanya 'ada yang mau ditanyakan', 'ada lagi yang mau kamu tanyakan', "
            "'butuh bantuan apa', 'ada lagi', atau 'mau tanyakan apa lagi'. "
            "Jawab langsung, lalu berhenti — jangan wawancara user."
            if bdv.questions.value == "NONE" or bdv.question_budget <= 0
            else (
                "Ask at most one clarifying question only if you cannot answer without a missing fact. "
                "Never ask a check-in, follow-up, or 'anything else' closer."
            )
        ),
        "Avoid robotic acknowledgments, canned closings, and over-explaining the obvious.",
    ]
    for phrase in profile.lexicon_avoided:
        if phrase.strip():
            fragments.append(f"Never say: {phrase.strip()}")

    return ExpressionConstraints(
        effective_warmth=effective_warmth,
        voice_register=register,
        max_words=max_words,
        max_sentences=max_sentences,
        question_budget=bdv.question_budget,
        tone_shift=bdv.tone_shift,
        prompt_fragments=fragments,
        template_ack=None,
    )
