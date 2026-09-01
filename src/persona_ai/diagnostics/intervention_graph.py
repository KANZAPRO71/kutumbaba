"""Intervention Interaction Graph — bundle simulation, synergy/conflict detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from itertools import combinations

from persona_ai.behavior.interpret import interpret
from persona_ai.core.types import ArcPhase, BehaviorInput, ConversationArc, Message, SpeakAction, TurnHistory
from persona_ai.diagnostics.counterfactual import (
    CounterfactualReport,
    Intervention,
    _delta,
    _expected_speak,
    _propose_interventions,
    _side_effect_risk,
    analyze_counterfactuals,
    simulate_intervention,
)
from persona_ai.diagnostics.failure_taxonomy import FailureClass, FailureEvent, FailureReport
from persona_ai.diagnostics.intervention_policy import InterventionPolicy, PolicyReport, format_policy_trace, root_cause_for_failure
from persona_ai.diagnostics.turn_context import TurnCausalContext
from persona_ai.sim.drift_harness import SessionReport, TurnRecord


class InteractionKind(str, Enum):
    SYNERGY = "synergy"
    CONFLICT = "conflict"
    REDUNDANT = "redundant"
    NEUTRAL = "neutral"
    DOMINANCE = "dominance"  # one subsumes the other


@dataclass
class InteractionEdge:
    a_id: str
    b_id: str
    kind: InteractionKind
    combined_speak: SpeakAction
    speak_a: SpeakAction
    speak_b: SpeakAction
    conflicts: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class InterventionBundle:
    intervention_ids: list[str]
    merged: Intervention
    combined_delta: float
    combined_risk: str
    counterfactual_speak: SpeakAction
    fixes_failure: bool
    regression_count: int
    patch_conflicts: list[str]
    score: float
    patch_hints: list[str] = field(default_factory=list)


@dataclass
class InterventionGraphNode:
    failure: FailureEvent
    expected_speak: SpeakAction
    baseline_speak: SpeakAction
    edges: list[InteractionEdge]
    bundles: list[InterventionBundle]
    optimal_bundle: InterventionBundle | None
    recommendation: str


@dataclass
class InterventionGraphReport:
    nodes: list[InterventionGraphNode]
    debug_trace: str = ""


def merge_interventions(interventions: list[Intervention], bundle_id: str | None = None) -> tuple[Intervention, list[str]]:
    """Merge patches; return merged intervention + key conflicts."""
    intent: dict = {}
    hist: dict = {}
    conflicts: list[str] = []
    layers: list[str] = []
    signals: list[str] = []
    hints: list[str] = []

    for iv in interventions:
        layers.append(iv.layer)
        signals.append(iv.signal)
        if iv.patch_hint:
            hints.append(iv.patch_hint)
        for k, v in iv.intent_patch.items():
            if k in intent and intent[k] != v:
                conflicts.append(f"intent.{k}: {intent[k]!r} vs {v!r}")
            intent[k] = v
        for k, v in iv.history_patch.items():
            if k in hist and hist[k] != v:
                conflicts.append(f"history.{k}: {hist[k]!r} vs {v!r}")
            hist[k] = v

    bid = bundle_id or "+".join(iv.id for iv in interventions)
    merged = Intervention(
        id=bid,
        layer=layers[0] if len(set(layers)) == 1 else "multi",
        signal="+".join(signals[:3]),
        intent_patch=intent,
        history_patch=hist,
        description=f"Bundle: {', '.join(iv.id for iv in interventions)}",
        patch_hint=" | ".join(hints),
    )
    return merged, conflicts


def simulate_bundle(
    turn: TurnRecord,
    history: TurnHistory,
    arc: ConversationArc | None,
    interventions: list[Intervention],
) -> tuple[SpeakAction, list[str]]:
    merged, conflicts = merge_interventions(interventions)
    speak = simulate_intervention(turn, history, arc, merged)
    return speak, conflicts


def _classify_pair(
    a: Intervention,
    b: Intervention,
    speak_a: SpeakAction,
    speak_b: SpeakAction,
    speak_ab: SpeakAction,
    expected: SpeakAction,
    conflicts: list[str],
) -> InteractionEdge:
    fixes_a = speak_a == expected
    fixes_b = speak_b == expected
    fixes_ab = speak_ab == expected

    if conflicts:
        kind = InteractionKind.CONFLICT
        note = f"Patch key collision: {'; '.join(conflicts)}"
    elif speak_a == speak_b == speak_ab:
        if fixes_a:
            kind = InteractionKind.REDUNDANT
            note = "Same outcome — pick lower delta singleton"
        else:
            kind = InteractionKind.NEUTRAL
            note = "No fix alone or together"
    elif fixes_a and not fixes_b and fixes_ab and speak_ab == speak_a:
        kind = InteractionKind.DOMINANCE
        note = f"{a.id} dominates {b.id}"
    elif fixes_b and not fixes_a and fixes_ab and speak_ab == speak_b:
        kind = InteractionKind.DOMINANCE
        note = f"{b.id} dominates {a.id}"
    elif fixes_ab and (fixes_a or fixes_b):
        kind = InteractionKind.SYNERGY
        note = "Combined fix holds — verify regression on other turns"
    elif fixes_a and fixes_b and speak_ab != expected:
        kind = InteractionKind.CONFLICT
        note = f"Fix alone but combined breaks -> {speak_ab.value}"
    else:
        kind = InteractionKind.NEUTRAL
        note = "No clear interaction"

    return InteractionEdge(a.id, b.id, kind, speak_ab, speak_a, speak_b, conflicts, note)


def _count_regressions(
    bundle: Intervention,
    target_index: int,
    session: SessionReport,
) -> int:
    """Turns where bundle changes speak away from baseline (proxy for regression)."""
    regressions = 0
    for i, turn in enumerate(session.turns):
        if i == target_index:
            continue
        hist = TurnHistory()
        if i > 0 and session.turns[i - 1].text:
            hist = TurnHistory(
                last_speaker="assistant",
                last_assistant_word_count=len(session.turns[i - 1].text.split()),
            )
        ctx = turn.context or TurnCausalContext()
        arc = ConversationArc(
            relational_warmth=turn.arc_warmth,
            arc_phase=ArcPhase(ctx.arc_phase) if ctx.arc_phase else ArcPhase.OPENING,
        )
        baseline = turn.speak
        patched = simulate_intervention(turn, hist, arc, bundle)
        if patched != baseline:
            regressions += 1
    return regressions


def _bundle_score(
    fixes: bool,
    delta: float,
    risk: str,
    regressions: int,
    conflicts: list[str],
    turn_count: int,
) -> float:
    if not fixes:
        return 0.0
    score = 100.0
    score -= delta * 25
    score -= regressions * (40 / max(turn_count, 1))
    score -= len(conflicts) * 15
    if risk == "high":
        score -= 20
    elif risk == "medium":
        score -= 8
    return max(0.0, round(score, 1))


def analyze_intervention_graph(
    failure_report: FailureReport,
    session: SessionReport,
    counterfactual: CounterfactualReport | None = None,
    policy: InterventionPolicy | None = None,
) -> tuple[InterventionGraphReport, PolicyReport | None]:
    policy = policy or InterventionPolicy()
    cf = counterfactual or analyze_counterfactuals(failure_report, session)
    graph_nodes: list[InterventionGraphNode] = []
    prune_stats: list = []

    for cf_node in cf.nodes:
        failure = cf_node.failure
        expected = cf_node.expected_speak
        idx = failure.turn_index
        if idx is None or idx >= len(session.turns):
            continue

        turn = session.turns[idx]
        ctx = turn.context or TurnCausalContext()
        turn_hist = TurnHistory()
        if idx > 0 and session.turns[idx - 1].text:
            turn_hist = TurnHistory(
                last_speaker="assistant",
                last_assistant_word_count=len(session.turns[idx - 1].text.split()),
            )
        arc = ConversationArc(
            relational_warmth=turn.arc_warmth,
            arc_phase=ArcPhase(ctx.arc_phase) if ctx.arc_phase else ArcPhase.OPENING,
        )

        fixers = [r.intervention for r in cf_node.results if r.fixes_failure and r.intervention.layer != "llm"]
        if not fixers:
            fixers = [r.intervention for r in cf_node.results if r.intervention.layer != "llm"][:5]

        root = root_cause_for_failure(failure, failure_report)
        fixers, pr = policy.prune(fixers or [r.intervention for r in cf_node.results[:5]], failure, ctx, root)
        prune_stats.append(pr)

        # Pairwise interaction edges (pruned set only)
        edges: list[InteractionEdge] = []
        speak_cache: dict[str, SpeakAction] = {}
        for iv in fixers:
            speak_cache[iv.id] = simulate_intervention(turn, turn_hist, arc, iv)

        for a, b in combinations(fixers, 2):
            if not policy.compatible_bundle([a.id, b.id]):
                continue
            speak_a = speak_cache[a.id]
            speak_b = speak_cache[b.id]
            speak_ab, conflicts = simulate_bundle(turn, turn_hist, arc, [a, b])
            edges.append(_classify_pair(a, b, speak_a, speak_b, speak_ab, expected, conflicts))

        # Bundle candidates: singletons + compatible pairs (no triples — policy max_bundle_size=2)
        bundle_candidates: list[list[Intervention]] = [[iv] for iv in fixers]
        for a, b in combinations(fixers, 2):
            if not policy.compatible_bundle([a.id, b.id]):
                continue
            speak_ab, _ = simulate_bundle(turn, turn_hist, arc, [a, b])
            if speak_ab == expected:
                bundle_candidates.append([a, b])

        bundles: list[InterventionBundle] = []
        seen_ids: set[str] = set()
        for combo in bundle_candidates:
            merged, conflicts = merge_interventions(combo)
            key = merged.id
            if key in seen_ids:
                continue
            seen_ids.add(key)
            speak = simulate_intervention(turn, turn_hist, arc, merged)
            fixes = speak == expected
            delta = _delta(merged.intent_patch, merged.history_patch, ctx)
            risk = _side_effect_risk(merged)
            reg = _count_regressions(merged, idx, session)
            score = _bundle_score(fixes, delta, risk, reg, conflicts, len(session.turns))
            bundles.append(InterventionBundle(
                intervention_ids=[iv.id for iv in combo],
                merged=merged,
                combined_delta=delta,
                combined_risk=risk,
                counterfactual_speak=speak,
                fixes_failure=fixes,
                regression_count=reg,
                patch_conflicts=conflicts,
                score=score,
                patch_hints=[iv.patch_hint for iv in combo if iv.patch_hint],
            ))

        bundles.sort(key=lambda b: (-b.score, b.combined_delta, b.regression_count))
        optimal = bundles[0] if bundles and bundles[0].fixes_failure else None
        rec = _graph_recommendation(optimal, edges, failure)

        graph_nodes.append(InterventionGraphNode(
            failure=failure,
            expected_speak=expected,
            baseline_speak=cf_node.baseline_speak,
            edges=edges,
            bundles=bundles,
            optimal_bundle=optimal,
            recommendation=rec,
        ))

    report = InterventionGraphReport(nodes=graph_nodes)
    report.debug_trace = format_intervention_graph(report)

    avoided = sum(pr.skipped_pairs for pr in prune_stats)
    policy_report = PolicyReport(
        predictions_by_failure={
            cf.nodes[i].failure.turn_index: pr.predictions
            for i, pr in enumerate(prune_stats)
            if cf.nodes[i].failure.turn_index is not None
        },
        prune_stats=prune_stats,
        total_simulations_avoided=avoided,
    )
    policy_report.debug_trace = format_policy_trace(policy_report, policy)

    for node in graph_nodes:
        if node.optimal_bundle and node.optimal_bundle.fixes_failure:
            policy.record_success(node.failure.failure_class, node.optimal_bundle.intervention_ids[0])

    return report, policy_report


def _graph_recommendation(
    optimal: InterventionBundle | None,
    edges: list[InteractionEdge],
    failure: FailureEvent,
) -> str:
    if optimal is None:
        conflicts = [e for e in edges if e.kind == InteractionKind.CONFLICT]
        if conflicts:
            return (
                f"No safe bundle for {failure.failure_class.value} — "
                f"{len(conflicts)} pairwise conflict(s). Use dominance or single-layer patch."
            )
        return f"No optimal bundle for {failure.failure_class.value}."

    ids = "+".join(optimal.intervention_ids)
    conflict_note = ""
    if optimal.patch_conflicts:
        conflict_note = f" Internal conflicts: {optimal.patch_conflicts}."
    reg_note = f" regressions={optimal.regression_count}" if optimal.regression_count else " regressions=0"
    hints = optimal.patch_hints[0] if len(optimal.patch_hints) == 1 else " | ".join(optimal.patch_hints[:2])
    return (
        f"Optimal bundle [{ids}] score={optimal.score} delta={optimal.combined_delta} "
        f"risk={optimal.combined_risk}{reg_note}.{conflict_note} "
        f"Patch: {hints}"
    )


def enrich_with_intervention_graph(
    failure_report: FailureReport,
    session: SessionReport,
) -> FailureReport:
    cf = failure_report.counterfactual
    graph, policy_report = analyze_intervention_graph(failure_report, session, cf)
    failure_report.intervention_graph = graph
    failure_report.intervention_policy = policy_report
    trace = graph.debug_trace
    if policy_report:
        trace += "\n\n" + policy_report.debug_trace
    failure_report.debug_trace = failure_report.debug_trace + "\n\n" + trace
    return failure_report


def format_intervention_graph(report: InterventionGraphReport) -> str:
    lines = ["=== Intervention Graph | bundle optimization ==="]
    if not report.nodes:
        lines.append("No intervention graphs built.")
        return "\n".join(lines)

    for node in report.nodes:
        f = node.failure
        turn = f"t{f.turn_index}" if f.turn_index is not None else "?"
        lines.append(f"\n[{turn}] {f.failure_class.value}")
        if node.optimal_bundle:
            ob = node.optimal_bundle
            lines.append(
                f"  OPTIMAL: {'+'.join(ob.intervention_ids)} "
                f"score={ob.score} delta={ob.combined_delta} reg={ob.regression_count}"
            )
            lines.append(f"           {node.recommendation}")
        conflicts = [e for e in node.edges if e.kind == InteractionKind.CONFLICT]
        synergies = [e for e in node.edges if e.kind in (InteractionKind.SYNERGY, InteractionKind.DOMINANCE)]
        if conflicts:
            lines.append(f"  CONFLICTS ({len(conflicts)}):")
            for e in conflicts[:3]:
                lines.append(f"    {e.a_id} x {e.b_id}: {e.note}")
        if synergies:
            lines.append(f"  SYNERGY/DOMINANCE ({len(synergies)}):")
            for e in synergies[:2]:
                lines.append(f"    {e.a_id} + {e.b_id}: {e.kind.value} -> {e.combined_speak.value}")
        if len(node.bundles) > 1:
            lines.append("  Top bundles:")
            for b in node.bundles[:3]:
                mark = "*" if b == node.optimal_bundle else " "
                lines.append(
                    f"   {mark} [{'+'.join(b.intervention_ids)}] score={b.score} "
                    f"fix={b.fixes_failure} reg={b.regression_count}"
                )
    return "\n".join(lines)
