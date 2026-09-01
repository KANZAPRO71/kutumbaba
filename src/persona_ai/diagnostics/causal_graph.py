"""Causal Failure Graph — failure → contributing signal decomposition."""

from __future__ import annotations

from dataclasses import dataclass, field

from enum import Enum

from persona_ai.diagnostics.failure_taxonomy import FailureClass, FailureEvent, FailureReport
from persona_ai.diagnostics.turn_context import TurnCausalContext
from persona_ai.sim.drift_harness import SessionReport, TurnRecord


class SignalSource(str, Enum):
    INTERPRET = "interpret"
    PRESSURE = "pressure"
    ARC = "arc"
    COHERENCE = "coherence"
    ARBITRATION = "arbitration"
    LLM = "llm"
    HISTORY = "history"


@dataclass
class CausalContribution:
    source: str
    signal: str
    value: float
    attribution: float
    explanation: str


@dataclass
class CausalNode:
    failure: FailureEvent
    contributions: list[CausalContribution]
    root_cause: str
    root_source: str
    chain_summary: str


@dataclass
class CausalReport:
    nodes: list[CausalNode]
    by_source: dict[str, float]
    debug_tree: str = ""


def _norm(weights: list[tuple[str, str, float, float, str]]) -> list[CausalContribution]:
    """Normalize (source, signal, value, weight, explanation) to attribution shares."""
    total = sum(w for _, _, _, w, _ in weights) or 1.0
    return [
        CausalContribution(
            source=src,
            signal=sig,
            value=val,
            attribution=round(w / total, 3),
            explanation=exp,
        )
        for src, sig, val, w, exp in weights
        if w > 0
    ]


def _ctx(turn: TurnRecord | None) -> TurnCausalContext:
    if turn and turn.context:
        return turn.context
    return TurnCausalContext()


def _node(failure: FailureEvent, contribs: list[CausalContribution]) -> CausalNode:
    if not contribs:
        contribs = [
            CausalContribution(
                source="unknown",
                signal="insufficient_context",
                value=0.0,
                attribution=1.0,
                explanation="No turn snapshot — re-run with causal context enabled.",
            )
        ]
    top = max(contribs, key=lambda c: c.attribution)
    chain = " + ".join(
        f"{c.source}.{c.signal}({c.attribution:.0%})"
        for c in sorted(contribs, key=lambda x: -x.attribution)[:3]
    )
    return CausalNode(
        failure=failure,
        contributions=contribs,
        root_cause=f"{top.source}.{top.signal}",
        root_source=top.source,
        chain_summary=f"{failure.failure_class.value} <- {chain}",
    )


# --- failure-specific decomposition rules ---

def _decompose_under_responsive(failure: FailureEvent, turn: TurnRecord) -> list[CausalContribution]:
    c = _ctx(turn)
    weights: list[tuple[str, str, float, float, str]] = []

    if c.intent_need < 0.4:
        weights.append((
            SignalSource.INTERPRET.value, "intent_need", c.intent_need,
            0.35 * (1 - c.intent_need),
            "Intent classified as low-need — RESPOND deprioritized in softmax.",
        ))
    if c.emotional_intensity > 0.5:
        weights.append((
            SignalSource.PRESSURE.value, "emotional_intensity", c.emotional_intensity,
            0.4 * c.emotional_intensity,
            "Emotional pressure steers toward ACK_ONLY path.",
        ))
    if c.is_vent:
        weights.append((
            SignalSource.INTERPRET.value, "is_vent", 1.0, 0.3,
            "Vent heuristic active — ACK preferred over full RESPOND.",
        ))
    ack_p = c.action_probabilities.get("ACK_ONLY", 0)
    resp_p = c.action_probabilities.get("RESPOND", 0)
    if ack_p > resp_p:
        weights.append((
            SignalSource.ARBITRATION.value, "ack_prob_dominant", ack_p - resp_p,
            0.25 * (ack_p - resp_p + 0.1),
            f"Softmax favored ACK ({ack_p:.2f}) over RESPOND ({resp_p:.2f}).",
        ))
    if c.arc_relational_warmth > 0.55:
        weights.append((
            SignalSource.ARC.value, "relational_warmth", c.arc_relational_warmth,
            0.15, "Arc warmth bias increases ack_bias in engine.",
        ))
    return _norm(weights)


def _decompose_defer_miss(failure: FailureEvent, turn: TurnRecord) -> list[CausalContribution]:
    c = _ctx(turn)
    weights: list[tuple[str, str, float, float, str]] = []

    if c.incompleteness_score < 0.5:
        weights.append((
            SignalSource.INTERPRET.value, "incompleteness_score", c.incompleteness_score,
            0.45 * (0.5 - c.incompleteness_score + 0.1),
            "Trailing thought not scored as incomplete — defer gate never opened.",
        ))
    if c.defer_pressure < 0.6:
        weights.append((
            SignalSource.PRESSURE.value, "defer_pressure", c.defer_pressure,
            0.35 * (0.6 - c.defer_pressure + 0.05),
            "Defer pressure below override threshold (0.6).",
        ))
    if c.emotional_intensity > 0.5 or c.is_vent:
        weights.append((
            SignalSource.INTERPRET.value, "vent_override", c.emotional_intensity,
            0.3, "Vent/emotion path may have preempted defer branch.",
        ))
    if "rhetorical_vent" in turn.reason_codes:
        weights.append((
            SignalSource.INTERPRET.value, "rhetorical_vent", 1.0, 0.25,
            "'...' treated as rhetorical vent, not incomplete utterance.",
        ))
    ack_p = c.action_probabilities.get("ACK_ONLY", 0)
    if ack_p > 0.3:
        weights.append((
            SignalSource.ARBITRATION.value, "ack_prob", ack_p, 0.2 * ack_p,
            "ACK softmax mass consumed turn that should defer.",
        ))
    return _norm(weights)


def _decompose_silence_miss(failure: FailureEvent, turn: TurnRecord) -> list[CausalContribution]:
    c = _ctx(turn)
    weights: list[tuple[str, str, float, float, str]] = []

    if not c.is_closure_ack:
        weights.append((
            SignalSource.INTERPRET.value, "closure_not_detected", 0.0, 0.4,
            "Short ack not classified as closure — silence gate skipped.",
        ))
    if c.assistant_load < 0.25:
        weights.append((
            SignalSource.HISTORY.value, "assistant_load", c.assistant_load,
            0.35, "Prior assistant turn too short — closure requires load >= 40 words.",
        ))
    if c.speak_pressure > c.silence_pressure:
        weights.append((
            SignalSource.PRESSURE.value, "speak_pressure", c.speak_pressure,
            0.3 * c.speak_pressure, "Speak pressure exceeded silence pressure in argmax.",
        ))
    if c.arc_phase not in ("winding_down", "resolution"):
        weights.append((
            SignalSource.ARC.value, "arc_phase", 0.0, 0.15,
            f"Arc phase '{c.arc_phase}' — no winding_down silence bias.",
        ))
    return _norm(weights)


def _decompose_over_responsive(failure: FailureEvent, turn: TurnRecord | None) -> list[CausalContribution]:
    c = _ctx(turn)
    weights: list[tuple[str, str, float, float, str]] = [
        (SignalSource.PRESSURE.value, "speak_pressure", c.speak_pressure, 0.35 * c.speak_pressure + 0.1,
         "High speak pressure across session."),
        (SignalSource.INTERPRET.value, "intent_need", c.intent_need, 0.25 * c.intent_need,
         "Intent need elevated — RESPOND favored."),
    ]
    if c.urgency > 0.5:
        weights.append((
            SignalSource.PRESSURE.value, "urgency", c.urgency, 0.2, "Urgency bias toward RESPOND.",
        ))
    return _norm(weights)


def _decompose_warmth_jump(failure: FailureEvent, turn: TurnRecord, prev: TurnRecord | None) -> list[CausalContribution]:
    c = _ctx(turn)
    prev_w = prev.effective_warmth if prev else c.anchor_baseline
    step = abs(turn.effective_warmth - prev_w)
    weights: list[tuple[str, str, float, float, str]] = []

    if abs(c.warmth_delta_from_anchor) > 0.08:
        weights.append((
            SignalSource.COHERENCE.value, "anchor_clamp", c.warmth_delta_from_anchor,
            0.35, "Coherence clamp allowed shift near anchor boundary.",
        ))
    if turn.tone_shift in ("WARMER", "SOFTER"):
        weights.append((
            SignalSource.ARBITRATION.value, "tone_shift", 0.0, 0.3,
            f"BDV authorized tone_shift={turn.tone_shift} (+0.08 coherence headroom).",
        ))
    if c.emotional_intensity > 0.5:
        weights.append((
            SignalSource.PRESSURE.value, "emotional_intensity", c.emotional_intensity,
            0.25 * c.emotional_intensity, "Emotional intensity raised expression warmth.",
        ))
    if c.arc_emotional_drift > 0.15:
        weights.append((
            SignalSource.ARC.value, "emotional_drift", c.arc_emotional_drift,
            0.2, "Arc emotional drift applies WARMER tone hint.",
        ))
    weights.append((
        SignalSource.COHERENCE.value, "warmth_step", step, 0.15 * min(step / 0.15, 1.0),
        f"Observed warmth step {step:.3f} between turns.",
    ))
    return _norm(weights)


def _decompose_llm(failure: FailureEvent, turn: TurnRecord) -> list[CausalContribution]:
    c = _ctx(turn)
    fc = failure.failure_class

    if fc == FailureClass.LLM_CPS_SPIKE:
        return _norm([
            (SignalSource.LLM.value, "cps_score", turn.cps_score, 0.6,
             "Chatbot phrase in generated text — prompt constraint insufficient."),
            (SignalSource.LLM.value, "prompt_fragments", 0.0, 0.25,
             "Review 'not customer service' fragment enforcement."),
            (SignalSource.PRESSURE.value, "question_budget", c.action_probabilities.get("RESPOND", 0), 0.15,
             "High engagement turn may invite helper phrasing."),
        ])
    if fc == FailureClass.LLM_OVERREACH:
        return _norm([
            (SignalSource.LLM.value, "render_bypass", 1.0, 0.7,
             "Text emitted despite SILENCE/DEFER — render early-exit failure."),
            (SignalSource.ARBITRATION.value, "speak_action", 0.0, 0.3,
             f"BDV said {turn.speak.value} but output was not suppressed."),
        ])
    if fc == FailureClass.LLM_ACK_BYPASS:
        return _norm([
            (SignalSource.LLM.value, "template_bypass", 1.0, 0.65,
             "ACK template short-circuit skipped — adapter invoked."),
            (SignalSource.ARBITRATION.value, "ack_only", 0.0, 0.35,
             "ACK_ONLY path should not call LLM."),
        ])
    if fc == FailureClass.LLM_WORD_OVERFLOW:
        wc = len(turn.text.split()) if turn.text else 0
        return _norm([
            (SignalSource.LLM.value, "word_count", float(wc), 0.55,
             "LLM exceeded VoiceDirective.max_words."),
            (SignalSource.LLM.value, "max_tokens", 120.0, 0.25,
             "Adapter max_tokens may be too high for constraint."),
            (SignalSource.PRESSURE.value, "engagement", c.emotional_intensity, 0.2,
             "High engagement may expand generation length."),
        ])
    return _norm([(SignalSource.LLM.value, "generation", 0.0, 1.0, "LLM surface failure.")])


def decompose_failure(
    failure: FailureEvent,
    session: SessionReport,
) -> CausalNode:
    turn: TurnRecord | None = None
    prev: TurnRecord | None = None
    if failure.turn_index is not None and failure.turn_index < len(session.turns):
        turn = session.turns[failure.turn_index]
        if failure.turn_index > 0:
            prev = session.turns[failure.turn_index - 1]

    fc = failure.failure_class
    contribs: list[CausalContribution] = []

    if fc == FailureClass.BDV_UNDER_RESPONSIVE and turn:
        contribs = _decompose_under_responsive(failure, turn)
    elif fc == FailureClass.BDV_DEFER_MISS and turn:
        contribs = _decompose_defer_miss(failure, turn)
    elif fc == FailureClass.BDV_SILENCE_MISS and turn:
        contribs = _decompose_silence_miss(failure, turn)
    elif fc == FailureClass.BDV_OVER_RESPONSIVE:
        contribs = _decompose_over_responsive(failure, turn)
    elif fc == FailureClass.COHERENCE_WARMTH_JUMP and turn:
        contribs = _decompose_warmth_jump(failure, turn, prev)
    elif fc in (
        FailureClass.LLM_CPS_SPIKE,
        FailureClass.LLM_OVERREACH,
        FailureClass.LLM_ACK_BYPASS,
        FailureClass.LLM_WORD_OVERFLOW,
        FailureClass.LLM_EMPTY_RESPONSE,
    ) and turn:
        contribs = _decompose_llm(failure, turn)
    elif fc == FailureClass.BDV_MISFIRE and turn:
        contribs = _decompose_under_responsive(failure, turn)
    elif fc == FailureClass.COHERENCE_ANCHOR_DRIFT:
        contribs = _norm([
            (SignalSource.COHERENCE.value, "anchor_ema", session.metrics.anchor_range, 0.5,
             "Session anchor baseline drifted — EMA alpha or clamp too loose."),
            (SignalSource.ARC.value, "relational_warmth", session.turns[-1].arc_warmth if session.turns else 0, 0.3,
             "Arc warmth trajectory pulling identity."),
            (SignalSource.PRESSURE.value, "emotional_intensity", 0.5, 0.2,
             "Repeated emotional turns shift anchor."),
        ])
    elif fc == FailureClass.BDV_MECHANICAL_PATTERN:
        contribs = _norm([
            (SignalSource.ARBITRATION.value, "softmax_collapse", 0.0, 0.45,
             "Action probabilities may be too peaked — low entropy."),
            (SignalSource.PRESSURE.value, "speak_pressure", 0.5, 0.35,
             "Dominant speak pressure channel."),
            (SignalSource.ARC.value, "phase", 0.0, 0.2,
             "Arc not injecting enough silence/ack variety."),
        ])

    return _node(failure, contribs)


def build_causal_report(failure_report: FailureReport, session: SessionReport) -> CausalReport:
    nodes = [decompose_failure(ev, session) for ev in failure_report.events]
    by_source: dict[str, float] = {}
    for node in nodes:
        for c in node.contributions:
            by_source[c.source] = by_source.get(c.source, 0.0) + c.attribution

    report = CausalReport(nodes=nodes, by_source=by_source)
    report.debug_tree = format_causal_tree(report)
    return report


def enrich_with_causality(
    failure_report: FailureReport,
    session: SessionReport,
) -> FailureReport:
    """Attach causal graph to an existing failure report."""
    causal = build_causal_report(failure_report, session)
    failure_report.causal = causal
    failure_report.debug_trace = failure_report.debug_trace + "\n\n" + causal.debug_tree
    return failure_report


def format_causal_tree(report: CausalReport) -> str:
    if not report.nodes:
        return "=== Causal Graph | no failures to decompose ==="

    lines = ["=== Causal Graph | root-cause decomposition ==="]
    if report.by_source:
        ranked = sorted(report.by_source.items(), key=lambda x: -x[1])
        lines.append("Session attribution by source: " + ", ".join(f"{k}={v:.2f}" for k, v in ranked))

    for node in report.nodes:
        f = node.failure
        turn = f"t{f.turn_index}" if f.turn_index is not None else "session"
        lines.append(f"\n[{turn}] {f.failure_class.value}")
        lines.append(f"  root: {node.root_cause}")
        lines.append(f"  chain: {node.chain_summary}")
        for c in sorted(node.contributions, key=lambda x: -x.attribution):
            lines.append(
                f"    {c.source}.{c.signal} = {c.value:.3f} ({c.attribution:.0%}) - {c.explanation}"
            )
    return '\n'.join(lines)
