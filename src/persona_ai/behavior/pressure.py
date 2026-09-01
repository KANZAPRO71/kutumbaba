"""Context pressure formulas — v0."""

from __future__ import annotations

from persona_ai.core.types import (
    BehaviorInput,
    ContextPressureScore,
    IntentInterpretation,
    ResponseLength,
    TurnHistory,
    clamp,
)


def _verbosity_score(length: ResponseLength) -> float:
    return {ResponseLength.MINIMAL: 0.2, ResponseLength.NORMAL: 0.5, ResponseLength.EXPAND: 0.9}[length]


def compute_pressure(
    intent: IntentInterpretation,
    history: TurnHistory,
    inp: BehaviorInput,
) -> ContextPressureScore:
    policy_must = any(s.type == "must_respond" for s in inp.policy_signals)

    u = clamp(
        0.5 * float(intent.is_direct_question)
        + 0.3 * float(intent.is_command)
        + 0.2 * float(policy_must)
        + 0.1 * intent.intent_need
    )

    vent_match = 1.0 if intent.is_vent else 0.0
    excl = min(1.0, inp.message.text.count("!") * 0.2)
    e = clamp(0.6 * intent.emotional_load + 0.3 * vent_match + 0.1 * excl)

    closure = 1.0 if intent.is_closure_ack else 0.0
    m = clamp(0.1 * (1.0 - closure))

    x = clamp(0.4 * float(intent.is_direct_question) + 0.1 * float(inp.message.text.lower().startswith(("hi", "halo", "hai"))))

    a = clamp(
        0.5 * _verbosity_score(history.last_assistant_verbosity)
        + 0.3 * min(1.0, history.consecutive_assistant_turns / 3)
        + 0.2 * min(1.0, history.last_assistant_word_count / 200)
    )

    voice_pause = 0.0
    if inp.voice_pause_ms and inp.voice_pause_ms > 800:
        voice_pause = min(1.0, inp.voice_pause_ms / 1500)

    speak = clamp(
        0.30 * u
        + 0.15 * x
        + 0.20 * intent.intent_need
        + 0.10 * m
        - 0.15 * e * (1 - float(intent.is_direct_question))
        - 0.25 * a
        - 0.20 * closure
    )

    silence = clamp(
        0.25 * (1 - intent.intent_need)
        + 0.25 * e * (1 - float(intent.is_direct_question))
        + 0.20 * closure
        + 0.15 * a
        + 0.15 * intent.incompleteness_score
    )

    defer = clamp(
        0.50 * intent.incompleteness_score + 0.30 * voice_pause + 0.20 * (1 - u)
    )

    return ContextPressureScore(
        urgency=u,
        emotional_intensity=e,
        momentum=m,
        user_expectation=x,
        assistant_load=a,
        speak_pressure=speak,
        silence_pressure=silence,
        defer_pressure=defer,
    )
