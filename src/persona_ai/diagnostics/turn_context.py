"""Per-turn signal snapshot for causal attribution."""

from __future__ import annotations

from dataclasses import dataclass, field

from persona_ai.core.types import ConversationArc, IntentInterpretation


@dataclass
class TurnCausalContext:
    """Signals captured at decision time — inputs to causal graph."""

    intent_need: float = 0.0
    incompleteness_score: float = 0.0
    emotional_load: float = 0.0
    is_direct_question: bool = False
    is_vent: bool = False
    is_mixed_intent: bool = False
    is_confusion_signal: bool = False
    is_closure_ack: bool = False
    speak_pressure: float = 0.0
    silence_pressure: float = 0.0
    defer_pressure: float = 0.0
    emotional_intensity: float = 0.0
    assistant_load: float = 0.0
    urgency: float = 0.0
    action_probabilities: dict[str, float] = field(default_factory=dict)
    primary_reason: str = ""
    decision_confidence: float = 0.0
    arc_phase: str = ""
    arc_relational_warmth: float = 0.0
    arc_emotional_drift: float = 0.0
    anchor_baseline: float = 0.0
    warmth_delta_from_anchor: float = 0.0


def build_turn_context(
    intent: IntentInterpretation,
    bdv,
    arc: ConversationArc | None,
    anchor_baseline: float,
    effective_warmth: float,
) -> TurnCausalContext:
    pressure = bdv.pressure
    probs = bdv.reasoning.action_probabilities if bdv.reasoning else {}

    return TurnCausalContext(
        intent_need=intent.intent_need,
        incompleteness_score=intent.incompleteness_score,
        emotional_load=intent.emotional_load,
        is_direct_question=intent.is_direct_question,
        is_vent=intent.is_vent,
        is_mixed_intent=intent.is_mixed_intent,
        is_confusion_signal=intent.is_confusion_signal,
        is_closure_ack=intent.is_closure_ack,
        speak_pressure=pressure.speak_pressure if pressure else 0.0,
        silence_pressure=pressure.silence_pressure if pressure else 0.0,
        defer_pressure=pressure.defer_pressure if pressure else 0.0,
        emotional_intensity=pressure.emotional_intensity if pressure else 0.0,
        assistant_load=pressure.assistant_load if pressure else 0.0,
        urgency=pressure.urgency if pressure else 0.0,
        action_probabilities=dict(probs),
        primary_reason=bdv.reasoning.primary_reason if bdv.reasoning else "",
        decision_confidence=bdv.reasoning.confidence if bdv.reasoning else 0.0,
        arc_phase=arc.arc_phase.value if arc else "",
        arc_relational_warmth=arc.relational_warmth if arc else 0.0,
        arc_emotional_drift=arc.emotional_drift if arc else 0.0,
        anchor_baseline=anchor_baseline,
        warmth_delta_from_anchor=abs(effective_warmth - anchor_baseline),
    )
