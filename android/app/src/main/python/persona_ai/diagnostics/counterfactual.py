"""Counterfactual Fix Engine v1 — simulate interventions, rank minimal fixes."""

from __future__ import annotations

from dataclasses import dataclass, field

from persona_ai.behavior.engine import decide_with_intent
from persona_ai.behavior.interpret import interpret
from persona_ai.core.types import (
    ArcPhase,
    BehaviorInput,
    ConversationArc,
    IntentDepth,
    Message,
    SpeakAction,
    TurnHistory,
)
from persona_ai.diagnostics.failure_taxonomy import FailureClass, FailureEvent, FailureReport
from persona_ai.diagnostics.turn_context import TurnCausalContext
from persona_ai.sim.drift_harness import SessionReport, TurnRecord


@dataclass
class Intervention:
    id: str
    layer: str
    signal: str
    intent_patch: dict = field(default_factory=dict)
    history_patch: dict = field(default_factory=dict)
    description: str = ""
    patch_hint: str = ""


@dataclass
class CounterfactualResult:
    intervention: Intervention
    baseline_speak: SpeakAction
    counterfactual_speak: SpeakAction
    expected_speak: SpeakAction
    fixes_failure: bool
    delta_magnitude: float
    side_effect_risk: str
    confidence: float


@dataclass
class CounterfactualNode:
    failure: FailureEvent
    expected_speak: SpeakAction
    baseline_speak: SpeakAction
    results: list[CounterfactualResult]
    minimal_fix: CounterfactualResult | None
    recommendation: str


@dataclass
class CounterfactualReport:
    nodes: list[CounterfactualNode]
    fixable_count: int
    debug_trace: str = ""


def _expected_speak(failure: FailureEvent) -> SpeakAction | None:
    mapping = {
        FailureClass.BDV_UNDER_RESPONSIVE: SpeakAction.RESPOND,
        FailureClass.BDV_OVER_RESPONSIVE: SpeakAction.SILENCE,
        FailureClass.BDV_DEFER_MISS: SpeakAction.DEFER,
        FailureClass.BDV_SILENCE_MISS: SpeakAction.SILENCE,
        FailureClass.BDV_MISFIRE: SpeakAction.RESPOND,
    }
    return mapping.get(failure.failure_class)


def _delta(intent_patch: dict, history_patch: dict, ctx: TurnCausalContext) -> float:
    total = 0.0
    baseline = {
        "intent_need": ctx.intent_need,
        "incompleteness_score": ctx.incompleteness_score,
        "is_direct_question": float(ctx.is_direct_question),
        "is_vent": float(ctx.is_vent),
        "is_mixed_intent": float(ctx.is_mixed_intent),
        "is_closure_ack": float(ctx.is_closure_ack),
        "requires_response": float(ctx.intent_need >= 0.5),
    }
    for k, v in intent_patch.items():
        if k in baseline and isinstance(v, (int, float)):
            total += abs(float(v) - baseline[k])
        elif k in ("is_direct_question", "is_vent", "is_mixed_intent", "is_closure_ack", "requires_response"):
            total += 0.35
        else:
            total += 0.2
    for k, v in history_patch.items():
        if k == "last_assistant_word_count":
            total += min(1.0, abs(v - 40) / 120)
        else:
            total += 0.15
    return round(min(1.0, total), 3)


def _side_effect_risk(intervention: Intervention) -> str:
    n = len(intervention.intent_patch) + len(intervention.history_patch)
    flips = sum(
        1 for k in ("is_vent", "is_direct_question", "is_mixed_intent", "is_closure_ack")
        if k in intervention.intent_patch
    )
    if flips >= 2 or n >= 4:
        return "high"
    if flips == 1 or n >= 2:
        return "medium"
    return "low"


def _propose_interventions(
    failure: FailureEvent,
    ctx: TurnCausalContext,
    turn: TurnRecord,
) -> list[Intervention]:
    fc = failure.failure_class
    interventions: list[Intervention] = []

    if fc in (FailureClass.BDV_UNDER_RESPONSIVE, FailureClass.BDV_MISFIRE):
        interventions.extend([
            Intervention(
                "raise_intent_need",
                "interpret",
                "intent_need",
                intent_patch={
                    "intent_need": 0.65,
                    "requires_response": True,
                    "depth": IntentDepth.MODERATE,
                },
                description="Raise intent_need for indirect instruction / question chains",
                patch_hint="interpret.py: detect indirect requests ('explain', 'properly') -> intent_need>=0.6",
            ),
            Intervention(
                "classify_direct_question",
                "interpret",
                "is_direct_question",
                intent_patch={
                    "is_direct_question": True,
                    "intent_need": 0.6,
                    "requires_response": True,
                    "depth": IntentDepth.MODERATE,
                },
                description="Reclassify utterance as direct question",
                patch_hint="interpret.py: broaden question_shape for instruction chains",
            ),
            Intervention(
                "mixed_intent_priority",
                "interpret",
                "is_mixed_intent",
                intent_patch={
                    "is_mixed_intent": True,
                    "is_vent": False,
                    "intent_need": 0.65,
                    "requires_response": True,
                },
                description="Treat as mixed intent (emotion + request) not pure vent",
                patch_hint="interpret.py: pivot + request verb -> mixed_intent",
            ),
        ])
    elif fc == FailureClass.BDV_DEFER_MISS:
        interventions.extend([
            Intervention(
                "raise_incompleteness",
                "interpret",
                "incompleteness_score",
                intent_patch={"incompleteness_score": 0.8, "depth": IntentDepth.NONE, "intent_need": 0.0},
                description="Score trailing 'hmm/sebenarnya' as incomplete utterance",
                patch_hint="interpret.py: trailing 'sebenarnya' after ellipsis -> incompleteness=0.8",
            ),
            Intervention(
                "clear_vent_override",
                "interpret",
                "is_vent",
                intent_patch={
                    "incompleteness_score": 0.8,
                    "is_vent": False,
                    "emotional_load": 0.2,
                },
                description="Prevent vent path from overriding defer on trailing thoughts",
                patch_hint="interpret.py: incompleteness takes priority over vent when trailing defer markers",
            ),
            Intervention(
                "boost_defer_pressure",
                "pressure",
                "defer_pressure",
                intent_patch={"incompleteness_score": 0.65},
                description="Lower defer gate threshold via incompleteness floor",
                patch_hint="engine.py: defer branch if incompleteness>=0.45 OR defer_pressure>0.5",
            ),
        ])
    elif fc == FailureClass.BDV_SILENCE_MISS:
        interventions.extend([
            Intervention(
                "seed_closure_history",
                "history",
                "assistant_load",
                history_patch={"last_assistant_word_count": 120, "last_speaker": "assistant"},
                description="Ensure prior assistant turn meets closure word threshold",
                patch_hint="session: persist assistant word count accurately across turns",
            ),
            Intervention(
                "mark_closure_ack",
                "interpret",
                "is_closure_ack",
                intent_patch={
                    "is_closure_ack": True,
                    "depth": IntentDepth.NONE,
                    "intent_need": 0.0,
                    "requires_response": False,
                },
                description="Classify short ack as closure after long assistant",
                patch_hint="interpret.py: closure_ack when ack + assistant_load>=40",
            ),
        ])
    elif fc == FailureClass.BDV_OVER_RESPONSIVE:
        interventions.extend([
            Intervention(
                "raise_silence_pressure",
                "pressure",
                "silence_pressure",
                intent_patch={"intent_need": 0.0, "requires_response": False, "depth": IntentDepth.NONE},
                description="Suppress respond intent on low-need turns",
                patch_hint="pressure.py: increase silence weight when assistant_load high",
            ),
        ])
    elif fc in (
        FailureClass.LLM_OVERREACH,
        FailureClass.LLM_ACK_BYPASS,
        FailureClass.LLM_CPS_SPIKE,
        FailureClass.LLM_WORD_OVERFLOW,
    ):
        interventions.append(Intervention(
            "render_early_exit",
            "llm",
            "render",
            description="Enforce render() early exit for SILENCE/DEFER/ACK template",
            patch_hint="adapter.py: return None/template before adapter.complete()",
        ))

    # Causal-guided extras from turn context
    if ctx.intent_need < 0.4 and fc == FailureClass.BDV_UNDER_RESPONSIVE:
        interventions.append(Intervention(
            "causal_intent_floor",
            "interpret",
            "intent_need",
            intent_patch={"intent_need": max(0.55, ctx.intent_need + 0.35), "requires_response": True},
            description=f"Causal: intent_need={ctx.intent_need:.2f} too low",
            patch_hint=f"Set intent_need floor to {max(0.55, ctx.intent_need + 0.35):.2f} for this archetype",
        ))

    if ctx.incompleteness_score < 0.5 and fc == FailureClass.BDV_DEFER_MISS:
        if "rhetorical_vent" in turn.reason_codes:
            interventions.append(Intervention(
                "disable_rhetorical_on_trailing",
                "interpret",
                "rhetorical_vent",
                intent_patch={"incompleteness_score": 0.8, "is_vent": False, "is_rhetorical": False},
                description="Don't treat trailing defer markers as rhetorical vent",
                patch_hint="interpret.py: 'sebenarnya' trailing != rhetorical vent even with '...'",
            ))

    return interventions


def simulate_intervention(
    turn: TurnRecord,
    history: TurnHistory,
    arc: ConversationArc | None,
    intervention: Intervention,
) -> SpeakAction:
    """Re-run decision kernel with patched signals."""
    if intervention.layer == "llm":
        return turn.speak  # LLM fixes are out-of-band for BDV sim

    intent = interpret(Message.from_text("user", turn.user_text), history.last_assistant_word_count)
    hist = history.model_copy(update=intervention.history_patch) if intervention.history_patch else history

    if intervention.intent_patch:
        intent = intent.model_copy(update=intervention.intent_patch)

    inp = BehaviorInput(message=Message.from_text("user", turn.user_text), history=hist, arc=arc)
    return decide_with_intent(inp, intent).speak


def evaluate_intervention(
    failure: FailureEvent,
    turn: TurnRecord,
    history: TurnHistory,
    arc: ConversationArc | None,
    expected: SpeakAction,
    intervention: Intervention,
) -> CounterfactualResult:
    ctx = turn.context or TurnCausalContext()
    baseline = turn.speak
    cf_speak = simulate_intervention(turn, history, arc, intervention)
    fixes = cf_speak == expected
    delta = _delta(intervention.intent_patch, intervention.history_patch, ctx)
    risk = _side_effect_risk(intervention)
    confidence = 0.9 if fixes and risk == "low" else (0.75 if fixes else 0.3)
    return CounterfactualResult(
        intervention=intervention,
        baseline_speak=baseline,
        counterfactual_speak=cf_speak,
        expected_speak=expected,
        fixes_failure=fixes,
        delta_magnitude=delta,
        side_effect_risk=risk,
        confidence=confidence,
    )


def analyze_counterfactuals(
    failure_report: FailureReport,
    session: SessionReport,
    history: TurnHistory | None = None,
) -> CounterfactualReport:
    nodes: list[CounterfactualNode] = []
    hist = history or TurnHistory()

    for failure in failure_report.events:
        expected = _expected_speak(failure)
        if expected is None or failure.turn_index is None:
            continue
        idx = failure.turn_index
        if idx >= len(session.turns):
            continue
        turn = session.turns[idx]
        ctx = turn.context or TurnCausalContext()

        # Reconstruct history at turn time (approximate from prior assistant output)
        turn_hist = hist
        if idx > 0:
            prev = session.turns[idx - 1]
            if prev.text:
                wc = len(prev.text.split())
                turn_hist = TurnHistory(
                    last_speaker="assistant",
                    last_assistant_word_count=wc,
                    consecutive_assistant_turns=1,
                )

        arc = ConversationArc(
            relational_warmth=turn.arc_warmth,
            arc_phase=ArcPhase(ctx.arc_phase) if ctx.arc_phase else ArcPhase.OPENING,
            emotional_drift=ctx.arc_emotional_drift,
        )

        interventions = _propose_interventions(failure, ctx, turn)
        results = [
            evaluate_intervention(failure, turn, turn_hist, arc, expected, iv)
            for iv in interventions
        ]
        results.sort(key=lambda r: (-int(r.fixes_failure), r.delta_magnitude, r.side_effect_risk))

        minimal = next((r for r in results if r.fixes_failure), None)
        rec = _recommendation(minimal, failure, turn)
        nodes.append(CounterfactualNode(
            failure=failure,
            expected_speak=expected,
            baseline_speak=turn.speak,
            results=results,
            minimal_fix=minimal,
            recommendation=rec,
        ))

    report = CounterfactualReport(
        nodes=nodes,
        fixable_count=sum(1 for n in nodes if n.minimal_fix),
    )
    report.debug_trace = format_counterfactual_trace(report)
    return report


def _recommendation(fix: CounterfactualResult | None, failure: FailureEvent, turn: TurnRecord) -> str:
    if fix is None:
        return f"No single-signal patch fixes {failure.failure_class.value} on turn {failure.turn_index} — consider interaction rule."
    iv = fix.intervention
    return (
        f"Minimal fix: {iv.layer}.{iv.signal} ({iv.id}) "
        f"delta={fix.delta_magnitude:.2f} risk={fix.side_effect_risk} -> "
        f"{fix.baseline_speak.value} to {fix.counterfactual_speak.value}. "
        f"Patch: {iv.patch_hint or iv.description}"
    )


def enrich_with_counterfactuals(
    failure_report: FailureReport,
    session: SessionReport,
) -> FailureReport:
    cf = analyze_counterfactuals(failure_report, session)
    failure_report.counterfactual = cf
    failure_report.debug_trace = failure_report.debug_trace + "\n\n" + cf.debug_trace
    return failure_report


def format_counterfactual_trace(report: CounterfactualReport) -> str:
    lines = [
        f"=== Counterfactual Fix Engine | fixable {report.fixable_count}/{len(report.nodes)} ===",
    ]
    if not report.nodes:
        lines.append("No BDV counterfactuals to simulate.")
        return "\n".join(lines)

    for node in report.nodes:
        f = node.failure
        turn = f"t{f.turn_index}" if f.turn_index is not None else "?"
        lines.append(f"\n[{turn}] {f.failure_class.value}: {node.baseline_speak.value} -> want {node.expected_speak.value}")
        if node.minimal_fix:
            mf = node.minimal_fix
            iv = mf.intervention
            lines.append(f"  BEST: {iv.id} (delta={mf.delta_magnitude}, risk={mf.side_effect_risk})")
            lines.append(f"         {node.recommendation}")
        else:
            lines.append("  BEST: none — needs compound rule")
        for r in node.results[:3]:
            mark = "FIX" if r.fixes_failure else "   "
            lines.append(
                f"  [{mark}] {r.intervention.id}: -> {r.counterfactual_speak.value} "
                f"(delta={r.delta_magnitude}, risk={r.side_effect_risk})"
            )
    return "\n".join(lines)
