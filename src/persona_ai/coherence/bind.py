"""Coherence — v0.3 soft binding."""

from __future__ import annotations

from persona_ai.core.types import (
    BehaviorDirectiveVector,
    ConversationArc,
    ExpressionConstraints,
    IdentityAnchor,
    PersonalityProfile,
    VoiceDirective,
    clamp,
)


def bind(
    bdv: BehaviorDirectiveVector,
    expression: ExpressionConstraints,
    profile: PersonalityProfile,
    arc: ConversationArc | None = None,
    anchor: IdentityAnchor | None = None,
) -> VoiceDirective:
    anchor = anchor or IdentityAnchor()

    proposed = expression.effective_warmth
    extra = 0.08 if bdv.tone_shift.value in ("WARMER", "SOFTER") else 0.0
    lo = anchor.session_tone_baseline - anchor.max_drift_per_turn
    hi = anchor.session_tone_baseline + anchor.max_drift_per_turn + extra
    effective = clamp(proposed, lo, hi)
    effective = max(effective, profile.warmth - 0.2)

    fragments = list(expression.prompt_fragments)
    fragments.append("Respond as one person with one consistent voice this turn.")

    return VoiceDirective(
        speak=bdv.speak,
        effective_warmth=effective,
        max_words=expression.max_words,
        max_sentences=expression.max_sentences,
        question_budget=bdv.question_budget,
        tone_shift=bdv.tone_shift,
        prompt_fragments=fragments,
        template_ack=expression.template_ack,
        timing_delay_ms=bdv.timing_delay_ms,
    )


def update_anchor(anchor: IdentityAnchor, effective_warmth: float, alpha: float = 0.25) -> IdentityAnchor:
    baseline = (1 - alpha) * anchor.session_tone_baseline + alpha * effective_warmth
    return anchor.model_copy(update={"session_tone_baseline": baseline})
