"""Behavior decision kernel — v0.1 decide()."""

from __future__ import annotations

import math

from persona_ai.behavior.interpret import interpret
from persona_ai.behavior.pressure import compute_pressure
from persona_ai.core.types import (
    ArcPhase,
    BehaviorDirectiveVector,
    BehaviorInput,
    BehaviorReasoning,
    ConversationArc,
    IntentDepth,
    PolicySignal,
    QuestionPolicy,
    ResponseLength,
    SpeakAction,
    ToneShift,
    clamp,
)


def _softmax(logits: dict[str, float]) -> dict[str, float]:
    m = max(logits.values())
    exps = {k: math.exp(v - m) for k, v in logits.items()}
    total = sum(exps.values())
    return {k: v / total for k, v in exps.items()}


def _arc_biases(arc: ConversationArc | None) -> tuple[float, float, float, ToneShift]:
    """Returns speak_bias, silence_bias, ack_bias, tone_hint for arc minimal floor."""
    if arc is None:
        return 0.0, 0.0, 0.0, ToneShift.STABLE

    speak_bias = 0.0
    silence_bias = 0.0
    ack_bias = 0.0
    tone = ToneShift.STABLE

    if arc.arc_phase == ArcPhase.WINDING_DOWN:
        silence_bias += 0.8
        speak_bias -= 0.25

    if arc.relational_warmth > 0.55:
        ack_bias += 0.25
        tone = ToneShift.WARMER

    if arc.emotional_drift > 0.15:
        tone = ToneShift.WARMER

    return speak_bias, silence_bias, ack_bias, tone


def decide(inp: BehaviorInput) -> BehaviorDirectiveVector:
    intent = interpret(inp.message, inp.history.last_assistant_word_count)
    return decide_with_intent(inp, intent)


def decide_with_intent(inp: BehaviorInput, intent) -> BehaviorDirectiveVector:
    """Decision kernel with explicit intent — for counterfactual simulation."""
    pressure = compute_pressure(intent, inp.history, inp)
    policy_must = any(
        s.type == "must_respond" and s.reason in {"safety", "urgent", "policy"}
        for s in inp.policy_signals
    )

    speak_b, silence_b, ack_b, arc_tone = _arc_biases(inp.arc)

    # Priority overrides (v0 simplified OAL tier 0/1)
    if policy_must or (pressure.urgency > 0.7 and intent.is_direct_question):
        speak = SpeakAction.RESPOND
        primary = "Policy or urgent direct question"
        probs = {SpeakAction.RESPOND.value: 1.0}
        confidence = 0.95
    elif intent.is_mixed_intent or intent.is_confusion_signal:
        speak = SpeakAction.RESPOND
        primary = "Mixed emotion + question/confusion — answer first, brief empathy"
        probs = {SpeakAction.RESPOND.value: 0.88}
        confidence = 0.88
    elif "social_greeting" in intent.reason_codes:
        speak = SpeakAction.RESPOND
        primary = "Social greeting — spoken reply"
        probs = {SpeakAction.RESPOND.value: 0.9}
        confidence = 0.9
    elif "continuation_request" in intent.reason_codes:
        speak = SpeakAction.RESPOND
        primary = "User asks to continue the conversation"
        probs = {SpeakAction.RESPOND.value: 0.92}
        confidence = 0.92
    elif "frustrated_dismissal" in intent.reason_codes:
        speak = SpeakAction.ACK_ONLY
        primary = "Frustrated dismissal — brief warm ack"
        probs = {SpeakAction.ACK_ONLY.value: 0.86}
        confidence = 0.86
    elif intent.incompleteness_score >= 0.5 or pressure.defer_pressure > 0.6:
        speak = SpeakAction.DEFER
        primary = "Incomplete utterance — observe"
        probs = {SpeakAction.DEFER.value: 0.9}
        confidence = 0.88
    elif intent.is_closure_ack or (intent.depth == IntentDepth.NONE and intent.is_closure_ack):
        speak = SpeakAction.SILENCE
        primary = "Closure ack — wind down"
        probs = {SpeakAction.SILENCE.value: 0.84}
        confidence = 0.9
    elif intent.depth == IntentDepth.NONE and not intent.requires_response:
        speak = SpeakAction.SILENCE
        primary = "Low intent — no response needed"
        probs = {SpeakAction.SILENCE.value: 0.75}
        confidence = 0.85
    else:
        logits = {
            SpeakAction.RESPOND.value: 2.0 * pressure.speak_pressure + 1.5 * intent.intent_need + speak_b,
            SpeakAction.ACK_ONLY.value: 1.5 * pressure.emotional_intensity + 0.8 * (1 - intent.intent_need) + ack_b,
            SpeakAction.SILENCE.value: 2.0 * pressure.silence_pressure + silence_b,
            SpeakAction.DEFER.value: 2.5 * pressure.defer_pressure,
        }
        probs = _softmax(logits)
        speak = SpeakAction(max(probs, key=probs.get))
        confidence = probs[speak.value]
        primary = f"Argmax from pressure (p={confidence:.2f})"

    # Style from decision + arc floor
    tone = arc_tone
    if intent.is_vent and speak == SpeakAction.ACK_ONLY:
        tone = ToneShift.WARMER

    length = ResponseLength.NORMAL
    partial = False
    questions = QuestionPolicy.NONE
    q_budget = 0
    delay = 0
    engagement = 0.5

    if speak == SpeakAction.ACK_ONLY:
        length = ResponseLength.MINIMAL
        partial = True
        engagement = 0.35
        delay = 400
        if tone == ToneShift.STABLE and (inp.arc and inp.arc.relational_warmth > 0.5):
            tone = ToneShift.WARMER
    elif speak == SpeakAction.SILENCE:
        engagement = 0.0
    elif speak == SpeakAction.DEFER:
        engagement = 0.0
        delay = 1500
    elif speak == SpeakAction.RESPOND:
        engagement = 0.6
        if intent.is_mixed_intent or intent.is_confusion_signal:
            length = ResponseLength.NORMAL
            tone = ToneShift.WARMER
            partial = True
            questions = QuestionPolicy.CLARIFY_ONLY
            q_budget = 1 if intent.is_confusion_signal else 0
        elif intent.is_direct_question:
            questions = QuestionPolicy.NONE
            q_budget = 0

    reasoning = BehaviorReasoning(
        primary_reason=primary,
        reason_codes=intent.reason_codes + [speak.value.lower()],
        confidence=confidence,
        action_probabilities=probs if isinstance(probs, dict) else {speak.value: confidence},
    )

    return BehaviorDirectiveVector(
        speak=speak,
        length=length,
        questions=questions,
        question_budget=q_budget,
        tone_shift=tone,
        partial_response=partial,
        engagement_level=engagement,
        timing_delay_ms=delay,
        pressure=pressure,
        reasoning=reasoning,
    )


def execution_profile(bdv: BehaviorDirectiveVector) -> str:
    if bdv.speak in (SpeakAction.SILENCE, SpeakAction.DEFER):
        return "ghost"
    if bdv.speak == SpeakAction.ACK_ONLY and bdv.length == ResponseLength.MINIMAL and bdv.engagement_level < 0.45:
        return "whisper"
    if bdv.engagement_level >= 0.65 or bdv.tone_shift != ToneShift.STABLE:
        return "presence"
    if bdv.length == ResponseLength.EXPAND:
        return "focused"
    return "standard"
