"""Intervention Policy Layer v1 — priors, pruning, pattern memory."""

from __future__ import annotations

from dataclasses import dataclass, field

from persona_ai.diagnostics.counterfactual import Intervention
from persona_ai.diagnostics.failure_taxonomy import FailureClass, FailureEvent, FailureReport
from persona_ai.diagnostics.turn_context import TurnCausalContext


@dataclass
class PatchPrior:
    """Static prior — encodes recurring fix patterns from diagnostic runs."""

    patch_id: str
    failure_classes: list[FailureClass]
    weight: float
    layer: str
    root_signals: list[str] = field(default_factory=list)
    exclusivity_group: str | None = None
    avoids: list[str] = field(default_factory=list)


# Registry — distilled from causal + counterfactual smoke patterns
PATCH_PRIORS: list[PatchPrior] = [
    PatchPrior(
        "raise_incompleteness",
        [FailureClass.BDV_DEFER_MISS],
        0.92,
        "interpret",
        root_signals=["incompleteness_score", "rhetorical_vent"],
        exclusivity_group="incompleteness",
        avoids=["boost_defer_pressure"],
    ),
    PatchPrior(
        "boost_defer_pressure",
        [FailureClass.BDV_DEFER_MISS],
        0.72,
        "pressure",
        root_signals=["defer_pressure"],
        exclusivity_group="incompleteness",
        avoids=["raise_incompleteness", "clear_vent_override"],
    ),
    PatchPrior(
        "clear_vent_override",
        [FailureClass.BDV_DEFER_MISS],
        0.68,
        "interpret",
        root_signals=["vent_override", "is_vent"],
        exclusivity_group="incompleteness",
    ),
    PatchPrior(
        "raise_intent_need",
        [FailureClass.BDV_UNDER_RESPONSIVE, FailureClass.BDV_MISFIRE],
        0.88,
        "interpret",
        root_signals=["intent_need"],
        exclusivity_group="intent_need",
        avoids=["classify_direct_question", "mixed_intent_priority"],
    ),
    PatchPrior(
        "mixed_intent_priority",
        [FailureClass.BDV_UNDER_RESPONSIVE],
        0.75,
        "interpret",
        root_signals=["is_vent", "mixed"],
        exclusivity_group="intent_need",
    ),
    PatchPrior(
        "classify_direct_question",
        [FailureClass.BDV_UNDER_RESPONSIVE],
        0.70,
        "interpret",
        root_signals=["intent_need", "direct_question"],
        exclusivity_group="intent_need",
    ),
    PatchPrior(
        "seed_closure_history",
        [FailureClass.BDV_SILENCE_MISS],
        0.85,
        "history",
        root_signals=["assistant_load"],
    ),
    PatchPrior(
        "mark_closure_ack",
        [FailureClass.BDV_SILENCE_MISS],
        0.80,
        "interpret",
        root_signals=["closure"],
    ),
    PatchPrior(
        "raise_silence_pressure",
        [FailureClass.BDV_OVER_RESPONSIVE],
        0.82,
        "pressure",
        root_signals=["speak_pressure"],
    ),
    PatchPrior(
        "render_early_exit",
        [
            FailureClass.LLM_OVERREACH,
            FailureClass.LLM_ACK_BYPASS,
            FailureClass.LLM_CPS_SPIKE,
        ],
        0.90,
        "llm",
    ),
]


@dataclass
class PolicyPrediction:
    patch_id: str
    prior_score: float
    layer: str
    reason: str


@dataclass
class PruneResult:
    original_count: int
    pruned_count: int
    skipped_pairs: int
    search_reduction_pct: float
    predictions: list[PolicyPrediction]
    selected_ids: list[str]


@dataclass
class PolicyReport:
    predictions_by_failure: dict[int, list[PolicyPrediction]]
    prune_stats: list[PruneResult]
    total_simulations_avoided: int
    debug_trace: str = ""


class InterventionPolicy:
    """Lightweight policy — prior scoring + exclusivity pruning + pattern memory."""

    def __init__(self, max_interventions: int = 3, max_bundle_size: int = 2):
        self.max_interventions = max_interventions
        self.max_bundle_size = max_bundle_size
        self._success_memory: dict[tuple[str, str], int] = {}

    def score(
        self,
        intervention: Intervention,
        failure: FailureEvent,
        ctx: TurnCausalContext,
        root_cause: str | None = None,
    ) -> float:
        score = 0.0
        fc = failure.failure_class
        root = root_cause or ""

        for prior in PATCH_PRIORS:
            if prior.patch_id != intervention.id:
                continue
            if fc not in prior.failure_classes:
                continue
            score += prior.weight
            if prior.root_signals and any(s in root for s in prior.root_signals):
                score += 0.12
            if prior.layer == intervention.layer:
                score += 0.05

        mem_key = (fc.value, intervention.id)
        score += min(0.15, self._success_memory.get(mem_key, 0) * 0.03)

        if intervention.layer == "interpret" and root.startswith("interpret"):
            score += 0.08
        if intervention.layer == "pressure" and root.startswith("pressure"):
            score += 0.08

        if ctx.incompleteness_score < 0.3 and intervention.id == "raise_incompleteness":
            score += 0.1
        if ctx.intent_need < 0.4 and intervention.id in ("raise_intent_need", "mixed_intent_priority"):
            score += 0.1

        return round(score, 3)

    def predict(
        self,
        interventions: list[Intervention],
        failure: FailureEvent,
        ctx: TurnCausalContext,
        root_cause: str | None = None,
    ) -> list[PolicyPrediction]:
        preds: list[PolicyPrediction] = []
        for iv in interventions:
            s = self.score(iv, failure, ctx, root_cause)
            if s <= 0 and iv.layer == "llm":
                s = 0.5
            reason = f"prior={s:.2f} layer={iv.layer}"
            if root_cause:
                reason += f" root={root_cause}"
            preds.append(PolicyPrediction(iv.id, s, iv.layer, reason))
        preds.sort(key=lambda p: -p.prior_score)
        return preds

    def prune(
        self,
        interventions: list[Intervention],
        failure: FailureEvent,
        ctx: TurnCausalContext,
        root_cause: str | None = None,
    ) -> tuple[list[Intervention], PruneResult]:
        preds = self.predict(interventions, failure, ctx, root_cause)
        by_id = {iv.id: iv for iv in interventions}

        selected: list[Intervention] = []
        used_groups: set[str] = set()

        for p in preds:
            if len(selected) >= self.max_interventions:
                break
            iv = by_id.get(p.patch_id)
            if iv is None:
                continue
            group = _exclusivity_group(iv.id)
            if group and group in used_groups:
                continue
            selected.append(iv)
            if group:
                used_groups.add(group)

        n = len(interventions)
        k = len(selected)
        full_pairs = n * (n - 1) // 2 if n > 1 else 0
        pruned_pairs = k * (k - 1) // 2 if k > 1 else 0
        skipped = max(0, full_pairs - pruned_pairs)

        reduction = 0.0
        if n > 0:
            reduction = round((1 - k / n) * 100, 1)

        return selected, PruneResult(
            original_count=n,
            pruned_count=k,
            skipped_pairs=skipped,
            search_reduction_pct=reduction,
            predictions=preds,
            selected_ids=[iv.id for iv in selected],
        )

    def compatible_bundle(self, ids: list[str]) -> bool:
        if len(ids) > self.max_bundle_size:
            return False
        groups: set[str] = set()
        for pid in ids:
            g = _exclusivity_group(pid)
            if g:
                if g in groups:
                    return False
                groups.add(g)
        for prior in PATCH_PRIORS:
            if prior.patch_id in ids:
                if any(a in ids for a in prior.avoids):
                    return False
        return True

    def record_success(self, failure_class: FailureClass, patch_id: str) -> None:
        key = (failure_class.value, patch_id)
        self._success_memory[key] = self._success_memory.get(key, 0) + 1

    def top_prediction(
        self,
        failure: FailureEvent,
        ctx: TurnCausalContext,
        interventions: list[Intervention],
        root_cause: str | None = None,
    ) -> PolicyPrediction | None:
        preds = self.predict(interventions, failure, ctx, root_cause)
        return preds[0] if preds else None


def _exclusivity_group(patch_id: str) -> str | None:
    for prior in PATCH_PRIORS:
        if prior.patch_id == patch_id:
            return prior.exclusivity_group
    return None


def root_cause_for_failure(
    failure: FailureEvent,
    failure_report: FailureReport,
) -> str | None:
    if failure_report.causal is None:
        return None
    for node in failure_report.causal.nodes:
        if node.failure.turn_index == failure.turn_index and node.failure.failure_class == failure.failure_class:
            return node.root_cause
    return None


def build_policy_report(
    failure_report: FailureReport,
    session,
    counterfactual,
) -> PolicyReport:
    policy = InterventionPolicy()
    predictions_by_failure: dict[int, list[PolicyPrediction]] = {}
    prune_stats: list[PruneResult] = []
    avoided = 0

    if counterfactual is None:
        return PolicyReport({}, [], 0, "No counterfactual data.")

    for cf_node in counterfactual.nodes:
        idx = cf_node.failure.turn_index
        if idx is None:
            continue
        turn = session.turns[idx] if idx < len(session.turns) else None
        ctx = turn.context if turn and turn.context else TurnCausalContext()
        root = root_cause_for_failure(cf_node.failure, failure_report)

        all_iv = [r.intervention for r in cf_node.results]
        _, pr = policy.prune(all_iv, cf_node.failure, ctx, root)
        predictions_by_failure[idx] = pr.predictions
        prune_stats.append(pr)
        avoided += pr.skipped_pairs

        if cf_node.minimal_fix and cf_node.minimal_fix.fixes_failure:
            policy.record_success(cf_node.failure.failure_class, cf_node.minimal_fix.intervention.id)

    report = PolicyReport(predictions_by_failure, prune_stats, avoided)
    report.debug_trace = format_policy_trace(report, policy)
    return report


def format_policy_trace(report: PolicyReport, policy: InterventionPolicy) -> str:
    lines = [
        f"=== Intervention Policy | simulations avoided ~{report.total_simulations_avoided} pairs ===",
    ]
    for pr in report.prune_stats:
        if not pr.selected_ids:
            continue
        lines.append(
            f"  prune {pr.original_count}->{pr.pruned_count} "
            f"({pr.search_reduction_pct}% reduction) skip {pr.skipped_pairs} pairs"
        )
        top = pr.predictions[:2] if pr.predictions else []
        for p in top:
            lines.append(f"    prior: {p.patch_id} ({p.prior_score:.2f}) {p.layer}")
    if report.predictions_by_failure:
        lines.append("  Policy rule: one patch per exclusivity group (intent_need | incompleteness)")
    return "\n".join(lines)


def enrich_with_policy(
    failure_report: FailureReport,
    session,
) -> FailureReport:
    cf = failure_report.counterfactual
    policy_report = build_policy_report(failure_report, session, cf)
    failure_report.intervention_policy = policy_report
    failure_report.debug_trace = failure_report.debug_trace + "\n\n" + policy_report.debug_trace
    return failure_report
