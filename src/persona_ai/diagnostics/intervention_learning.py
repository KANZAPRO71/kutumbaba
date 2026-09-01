"""Intervention Prior Learning Layer v1.1 — fingerprint-aware priors + fast-path."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from persona_ai.diagnostics.counterfactual import Intervention
from persona_ai.diagnostics.failure_fingerprint import FingerprintReport
from persona_ai.diagnostics.fingerprint_learning import (
    FingerprintPatchLearner,
    FingerprintPatchPrediction,
    get_fp_learner,
)
from persona_ai.diagnostics.failure_taxonomy import FailureClass, FailureEvent, FailureReport
from persona_ai.diagnostics.intervention_policy import PATCH_PRIORS, InterventionPolicy
from persona_ai.diagnostics.turn_context import TurnCausalContext
from persona_ai.diagnostics.fast_path_controller import SCORING_SURFACE_VERSION


@dataclass
class LearnedPrior:
    failure_class: str
    patch_id: str
    context_key: str
    successes: int = 0
    attempts: int = 0

    @property
    def success_rate(self) -> float:
        return (self.successes + 1) / (self.attempts + 2)

    @property
    def confidence(self) -> float:
        return min(1.0, self.attempts / 5)


@dataclass
class LearnedPrediction:
    patch_id: str
    success_rate: float
    confidence: float
    blended_score: float
    source: str
    context_key: str
    reason: str
    fingerprint_id: str | None = None
    fp_score: float | None = None
    elasticity_weight: float | None = None


@dataclass
class FingerprintRecommendation:
    fingerprint_id: str
    patch_id: str
    score: float
    attempts: int
    fast_path: bool
    learner_eligible: bool = False
    promoted: bool = False
    elasticity_weight: float = 1.0
    effective_score: float | None = None
    s_final: float | None = None
    s_calibrated: float | None = None


@dataclass
class LearningReport:
    predictions: list[LearnedPrediction]
    fingerprint_recommendations: list[FingerprintRecommendation]
    fast_path_eligible: bool
    recommended_patch: str | None
    fast_path_fingerprint: str | None
    fast_path_score: float | None
    explicit_fallback: bool
    observations_recorded: int
    store_size: int
    fp_store_size: int = 0
    promoted_store_size: int = 0
    fast_path_elasticity: float | None = None
    fast_path_effective_score: float | None = None
    fast_path_s_final: float | None = None
    score_decomposition: dict | None = None
    geometry_valid: bool | None = None
    geometry_gate_pass: bool | None = None
    arbitration_feasible: bool | None = None
    debug_trace: str = ""


def _context_key(ctx: TurnCausalContext, root_cause: str | None) -> str:
    parts: list[str] = []
    if root_cause:
        parts.append(root_cause.split(".")[0])
    if ctx.incompleteness_score < 0.3:
        parts.append("low_inc")
    if ctx.intent_need < 0.4:
        parts.append("low_need")
    if ctx.is_vent:
        parts.append("vent")
    return "|".join(parts) if parts else "*"


def _fp_for_failure(failure_report: FailureReport, failure: FailureEvent) -> str | None:
    fp_report: FingerprintReport | None = failure_report.fingerprints
    if not fp_report:
        return None
    for item in fp_report.items:
        f = item.failure
        if f.turn_index == failure.turn_index and f.failure_class == failure.failure_class:
            return item.fingerprint.fingerprint_id
    return None


def _semantic_by_fp(failure_report: FailureReport) -> dict[str, str]:
    fp_report: FingerprintReport | None = failure_report.fingerprints
    if not fp_report:
        return {}
    return {item.fingerprint.fingerprint_id: item.fingerprint.semantic_key for item in fp_report.items}


class PriorLearner:
    """Legacy failure_class priors — fallback when fingerprint history is sparse."""

    CONFIDENCE_THRESHOLD = 0.6
    RATE_THRESHOLD = 0.55
    MIN_ATTEMPTS = 2

    def __init__(self, store_path: Path | None = None):
        self.store_path = store_path
        self._priors: dict[tuple[str, str, str], LearnedPrior] = {}
        self._session_observations = 0
        if store_path and store_path.exists():
            self._load()
        else:
            self._seed_from_static()

    def _key(self, failure_class: str, patch_id: str, context_key: str) -> tuple[str, str, str]:
        return (failure_class, patch_id, context_key)

    def _seed_from_static(self) -> None:
        for prior in PATCH_PRIORS:
            for fc in prior.failure_classes:
                k = self._key(fc.value, prior.patch_id, "*")
                if k in self._priors:
                    continue
                attempts = max(2, int(prior.weight * 5))
                successes = max(1, int(attempts * prior.weight))
                self._priors[k] = LearnedPrior(fc.value, prior.patch_id, "*", successes, attempts)

    def observe(
        self,
        failure_class: FailureClass,
        patch_id: str,
        success: bool,
        ctx: TurnCausalContext | None = None,
        root_cause: str | None = None,
    ) -> None:
        ctx_key = _context_key(ctx or TurnCausalContext(), root_cause)
        for key in (ctx_key, "*"):
            k = self._key(failure_class.value, patch_id, key)
            if k not in self._priors:
                self._priors[k] = LearnedPrior(failure_class.value, patch_id, key)
            lp = self._priors[k]
            lp.attempts += 1
            if success:
                lp.successes += 1
        self._session_observations += 1

    def predict_rate(
        self,
        failure_class: FailureClass,
        patch_id: str,
        ctx: TurnCausalContext,
        root_cause: str | None = None,
    ) -> tuple[float, float]:
        ctx_key = _context_key(ctx, root_cause)
        specific = self._priors.get(self._key(failure_class.value, patch_id, ctx_key))
        global_p = self._priors.get(self._key(failure_class.value, patch_id, "*"))

        if specific and global_p:
            w = min(0.7, specific.confidence)
            rate = w * specific.success_rate + (1 - w) * global_p.success_rate
            conf = max(specific.confidence, global_p.confidence * 0.5)
            return round(rate, 3), round(conf, 3)
        if specific:
            return specific.success_rate, specific.confidence
        if global_p:
            return global_p.success_rate, global_p.confidence
        return 0.5, 0.0

    def predict_best(
        self,
        failure: FailureEvent,
        interventions: list[Intervention],
        ctx: TurnCausalContext,
        root_cause: str | None,
        static_policy: InterventionPolicy | None = None,
    ) -> list[LearnedPrediction]:
        static_policy = static_policy or InterventionPolicy()
        preds: list[LearnedPrediction] = []
        ctx_key = _context_key(ctx, root_cause)

        for iv in interventions:
            rate, conf = self.predict_rate(failure.failure_class, iv.id, ctx, root_cause)
            static = static_policy.score(iv, failure, ctx, root_cause)
            blend = round(0.45 * rate + 0.35 * static / 1.5 + 0.2 * conf, 3)
            source = "learned" if conf >= 0.4 else "static"
            if conf >= 0.4 and static > 0.5:
                source = "blended"
            preds.append(LearnedPrediction(
                patch_id=iv.id,
                success_rate=rate,
                confidence=conf,
                blended_score=blend,
                source=source,
                context_key=ctx_key,
                reason=f"rate={rate:.2f} conf={conf:.2f} static={static:.2f}",
            ))
        preds.sort(key=lambda p: -p.blended_score)
        return preds

    def save(self) -> None:
        if not self.store_path:
            return
        data = [asdict(v) for v in self._priors.values()]
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self.store_path or not self.store_path.exists():
            return
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        for row in data:
            k = (row["failure_class"], row["patch_id"], row["context_key"])
            self._priors[k] = LearnedPrior(**row)

    @property
    def store_size(self) -> int:
        return len(self._priors)


def _blend_fp_and_legacy(
    fp_pred: FingerprintPatchPrediction,
    legacy: LearnedPrediction | None,
) -> LearnedPrediction:
    if legacy is None:
        return LearnedPrediction(
            patch_id=fp_pred.patch_id,
            success_rate=fp_pred.success_rate,
            confidence=fp_pred.confidence,
            blended_score=fp_pred.score,
            source="fingerprint" if fp_pred.attempts > 0 else "static",
            context_key="*",
            reason=fp_pred.reason,
            fingerprint_id=fp_pred.fingerprint_id,
            fp_score=fp_pred.score,
        )
    blend = round(0.6 * fp_pred.score + 0.4 * legacy.blended_score, 3) if fp_pred.attempts > 0 else legacy.blended_score
    source = "fingerprint" if fp_pred.attempts >= 2 else legacy.source
    if fp_pred.attempts > 0 and legacy.confidence >= 0.4:
        source = "fp_blended"
    return LearnedPrediction(
        patch_id=fp_pred.patch_id,
        success_rate=fp_pred.success_rate if fp_pred.attempts > 0 else legacy.success_rate,
        confidence=max(fp_pred.confidence, legacy.confidence),
        blended_score=blend,
        source=source,
        context_key=legacy.context_key,
        reason=f"fp={fp_pred.reason} | {legacy.reason}",
        fingerprint_id=fp_pred.fingerprint_id,
        fp_score=fp_pred.score,
    )


def ingest_from_diagnostic_run(
    learner: PriorLearner,
    failure_report: FailureReport,
    session,
    fp_learner: FingerprintPatchLearner | None = None,
) -> int:
    """Record counterfactual outcomes keyed by fingerprint when available."""
    fp_learner = fp_learner or get_fp_learner()
    count = 0
    cf = failure_report.counterfactual
    graph = failure_report.intervention_graph
    if not cf:
        return 0

    for cf_node in cf.nodes:
        idx = cf_node.failure.turn_index
        if idx is None or idx >= len(session.turns):
            continue
        turn = session.turns[idx]
        ctx = turn.context or TurnCausalContext()
        root = None
        if failure_report.causal:
            for cn in failure_report.causal.nodes:
                if cn.failure.turn_index == idx:
                    root = cn.root_cause
                    break

        fp_id = _fp_for_failure(failure_report, cf_node.failure)

        for result in cf_node.results:
            learner.observe(
                cf_node.failure.failure_class,
                result.intervention.id,
                result.fixes_failure,
                ctx,
                root,
            )
            if fp_id:
                fp_learner.record_simulation(fp_id, result.intervention.id, fixes_failure=result.fixes_failure)
            count += 1

        if graph:
            for gn in graph.nodes:
                if gn.failure.turn_index == idx and gn.optimal_bundle:
                    patch_id = gn.optimal_bundle.intervention_ids[0]
                    learner.observe(
                        gn.failure.failure_class,
                        patch_id,
                        gn.optimal_bundle.fixes_failure,
                        ctx,
                        root,
                    )
                    if fp_id:
                        fp_learner.record_simulation(
                            fp_id, patch_id, fixes_failure=gn.optimal_bundle.fixes_failure
                        )
                    count += 1

    learner.save()
    if count:
        fp_learner.save()
    return count


def extract_recommended_patches(failure_report: FailureReport) -> dict[str, str]:
    lr = failure_report.intervention_learning
    if not lr:
        return {}
    return {rec.fingerprint_id: rec.patch_id for rec in lr.fingerprint_recommendations}


def build_learning_report(
    learner: PriorLearner,
    failure_report: FailureReport,
    session,
    fp_learner: FingerprintPatchLearner | None = None,
) -> LearningReport:
    fp_learner = fp_learner or get_fp_learner()
    from persona_ai.diagnostics.fast_path_controller import evaluate_runtime_score
    from persona_ai.diagnostics.promotion_gate import get_promoted_store

    promoted_store = get_promoted_store()
    predictions: list[LearnedPrediction] = []
    fp_recommendations: list[FingerprintRecommendation] = []
    fast_path = False
    recommended: str | None = None
    fast_path_fp: str | None = None
    fast_path_score: float | None = None
    fast_path_elasticity: float | None = None
    fast_path_effective: float | None = None
    fast_path_s_final: float | None = None
    score_decomposition: dict | None = None
    fallback = True
    blocked_reason: str | None = None
    geometry_valid: bool | None = None
    geometry_gate_pass: bool | None = None
    arbitration_feasible: bool | None = None
    policy = InterventionPolicy()

    cf = failure_report.counterfactual
    if not cf:
        report = LearningReport(
            predictions=[],
            fingerprint_recommendations=[],
            fast_path_eligible=False,
            recommended_patch=None,
            fast_path_fingerprint=None,
            fast_path_score=None,
            explicit_fallback=True,
            observations_recorded=learner._session_observations,
            store_size=learner.store_size,
            fp_store_size=fp_learner.store_size,
        )
        report.debug_trace = format_learning_trace(report, learner, fp_learner)
        return report

    for cf_node in cf.nodes:
        idx = cf_node.failure.turn_index
        if idx is None or idx >= len(session.turns):
            continue
        turn = session.turns[idx]
        ctx = turn.context or TurnCausalContext()
        root = None
        if failure_report.causal:
            for cn in failure_report.causal.nodes:
                if cn.failure.turn_index == idx:
                    root = cn.root_cause
                    break

        interventions = [r.intervention for r in cf_node.results if r.intervention.layer != "llm"]
        patch_ids = [iv.id for iv in interventions]
        legacy_preds = learner.predict_best(cf_node.failure, interventions, ctx, root, policy)
        legacy_by_patch = {p.patch_id: p for p in legacy_preds}

        fp_id = _fp_for_failure(failure_report, cf_node.failure)
        if fp_id and patch_ids:
            fp_preds = fp_learner.predict_best(fp_id, patch_ids)
            contract_records: list = []
            from persona_ai.diagnostics.cross_cluster_calibration import (
                CrossClusterStore,
                calibrate_cross_cluster_batch,
            )
            from persona_ai.diagnostics.explainability_dashboard import record_from_decomposition

            cal_store = CrossClusterStore()
            semantic_by_fp = _semantic_by_fp(failure_report)
            batch_items: list[tuple[str, str, Any]] = []
            blended_by_patch: dict[str, LearnedPrediction] = {}

            for fp_pred in fp_preds:
                blended = _blend_fp_and_legacy(fp_pred, legacy_by_patch.get(fp_pred.patch_id))
                learned_score = legacy_by_patch.get(fp_pred.patch_id)
                learned_val = learned_score.blended_score if learned_score else fp_pred.decayed_score
                decomp = evaluate_runtime_score(
                    fp_pred,
                    learned_score=learned_val,
                    fp_id=fp_id,
                    patch_id=fp_pred.patch_id,
                    store=promoted_store,
                    threshold=fp_learner.SCORE_THRESHOLD,
                )
                contract_records.append(
                    record_from_decomposition(decomp, fp_id=fp_id, patch_id=fp_pred.patch_id)
                )
                batch_items.append((fp_id, fp_pred.patch_id, decomp))
                blended_by_patch[fp_pred.patch_id] = blended

            calibrated_list, geometry_verdict, cross_results, gate_verdict = calibrate_cross_cluster_batch(
                batch_items,
                semantic_by_fp=semantic_by_fp,
                store=cal_store,
                persist=True,
            )
            cross_by_patch = {batch_items[i][1]: cross_results[i] for i in range(len(batch_items))}
            geometry_valid = geometry_verdict.valid
            geometry_gate_pass = gate_verdict.pass_gate if gate_verdict else geometry_valid
            if gate_verdict and not gate_verdict.pass_gate:
                geometry_valid = False

            from persona_ai.diagnostics.constraint_arbitration import arbitrate_from_calibration

            arbitration = arbitrate_from_calibration(
                calibrated_list,
                cross_results,
                [item[1] for item in batch_items],
                gate_verdict=gate_verdict,
            )
            arbitration_feasible = arbitration.batch_feasible
            arb_by_patch = {result.candidate.patch_id: result for result in arbitration.results}

            scored: list[tuple[LearnedPrediction, Any, Any, Any]] = []
            for i, cal in enumerate(calibrated_list):
                patch_id = batch_items[i][1]
                blended = blended_by_patch[patch_id]
                arb = arb_by_patch.get(patch_id)
                exec_score = arb.s_equilibrium if arb and arb.feasible else cal.s_arbitration
                blended.blended_score = exec_score
                blended.elasticity_weight = cal.decomp.elasticity_weight
                blended.fp_score = exec_score
                scored.append((blended, cal.decomp, cal, arb))
            scored.sort(key=lambda pair: -pair[0].blended_score)
            merged = [pair[0] for pair in scored]
            if merged:
                predictions.extend(merged[:2])
                top = merged[0]
                top_fp = next(p for p in fp_preds if p.patch_id == top.patch_id)
                top_decomp = next(d for b, d, _, _ in scored if b.patch_id == top.patch_id)
                top_cal = next(c for b, _, c, _ in scored if b.patch_id == top.patch_id)
                top_arb = next(a for b, _, _, a in scored if b.patch_id == top.patch_id)
                top_cross = cross_by_patch.get(top.patch_id)
                fast_path_s_final = (
                    top_arb.s_equilibrium
                    if top_arb and top_arb.feasible
                    else top_cal.s_arbitration
                )
                score_decomposition = top_decomp.why_score()
                score_decomposition["s_calibrated"] = top_cal.calibration.s_calibrated
                score_decomposition["calibration_delta"] = top_cal.calibration.calibration_delta
                if top_cross:
                    score_decomposition["semantic_cluster"] = top_cross.semantic_cluster
                    score_decomposition["local_delta"] = top_cross.local_delta
                    score_decomposition["shared_delta"] = top_cross.shared_delta
                    score_decomposition["tension_factor"] = top_cross.tension_factor
                if top_arb:
                    score_decomposition["s_equilibrium"] = top_arb.s_equilibrium
                    score_decomposition["constraint_energy"] = top_arb.energy.e_total
                    score_decomposition["arbitration_feasible"] = top_arb.feasible
                from persona_ai.diagnostics.runtime_soft_observer import emit_soft_snapshot_if_admitted

                soft_snap = emit_soft_snapshot_if_admitted(
                    fp_id=fp_id,
                    patch_id=top.patch_id,
                    calibrated_list=calibrated_list,
                    cross_results=cross_results,
                    gate_verdict=gate_verdict,
                    arbitration=arbitration,
                    semantic_by_fp=semantic_by_fp,
                    top_s_final=top_decomp.s_final,
                    top_s_calibrated=top_cal.calibration.s_calibrated,
                    top_s_arbitration=(
                        top_arb.s_equilibrium
                        if top_arb and top_arb.feasible
                        else top_cal.s_arbitration
                    ),
                )
                if soft_snap:
                    score_decomposition["soft_invariant_class"] = soft_snap.invariant_class
                    score_decomposition["soft_distance_to_anchor"] = soft_snap.soft_distance_to_anchor
                    if soft_snap.structural_drift_flag:
                        score_decomposition["structural_runtime_deformation"] = True
                    if soft_snap.ci_fixture_review_suggested:
                        score_decomposition["ci_fixture_review_suggested"] = True
                learner_ok = top_fp.effective_attempts >= fp_learner.MIN_EFFECTIVE_ATTEMPTS
                promoted_ok = top_decomp.trust_state == "active"
                fp_fast_path = (
                    top_arb.fast_path_eligible
                    if top_arb and top_arb.feasible and arbitration_feasible
                    else False
                )
                fp_recommendations.append(
                    FingerprintRecommendation(
                        fingerprint_id=fp_id,
                        patch_id=top.patch_id,
                        score=top_fp.score,
                        attempts=top_fp.attempts,
                        fast_path=fp_fast_path,
                        learner_eligible=learner_ok,
                        promoted=promoted_ok,
                        elasticity_weight=top_decomp.elasticity_weight,
                        effective_score=top_decomp.legacy_effective_score,
                        s_final=top_decomp.s_final,
                        s_calibrated=top_cal.calibration.s_calibrated,
                    )
                )
                if fp_fast_path:
                    fast_path = True
                    recommended = top.patch_id
                    fast_path_fp = fp_id
                    fast_path_score = top_fp.decayed_score
                    fast_path_elasticity = top_decomp.elasticity_weight
                    fast_path_effective = top_cal.calibration.s_calibrated
                    fallback = False
                elif learner_ok and top_decomp.trust_state == "unpromoted":
                    blocked_reason = "unpromoted"
                elif top_decomp.trust_state in ("degraded", "quarantined"):
                    blocked_reason = top_decomp.trust_state
                elif top_arb and top_arb.feasible and top_arb.s_equilibrium < fp_learner.SCORE_THRESHOLD:
                    blocked_reason = "s_equilibrium_below_threshold"
                elif not arbitration_feasible:
                    blocked_reason = "arbitration_infeasible"
                elif top_cal.s_arbitration < fp_learner.SCORE_THRESHOLD:
                    blocked_reason = "s_final_below_threshold"
                else:
                    blocked_reason = "insufficient_attempts"
            if contract_records:
                from persona_ai.diagnostics.explainability_dashboard import persist_run_records

                script_name = getattr(session, "script_name", "") or ""
                persist_run_records(
                    contract_records,
                    script_name=script_name,
                    source="learning_report",
                )
        elif legacy_preds:
            predictions.extend(legacy_preds[:2])

    report = LearningReport(
        predictions=predictions,
        fingerprint_recommendations=fp_recommendations,
        fast_path_eligible=fast_path,
        recommended_patch=recommended,
        fast_path_fingerprint=fast_path_fp,
        fast_path_score=fast_path_score,
        explicit_fallback=fallback,
        observations_recorded=learner._session_observations,
        store_size=learner.store_size,
        fp_store_size=fp_learner.store_size,
        promoted_store_size=promoted_store.active_count,
        fast_path_elasticity=fast_path_elasticity,
        fast_path_effective_score=fast_path_effective,
        fast_path_s_final=fast_path_s_final,
        score_decomposition=score_decomposition,
        geometry_valid=geometry_valid,
        geometry_gate_pass=geometry_gate_pass,
        arbitration_feasible=arbitration_feasible,
    )
    report.debug_trace = format_learning_trace(
        report,
        learner,
        fp_learner,
        blocked_reason=blocked_reason,
        score_decomposition=score_decomposition,
        geometry_valid=geometry_valid,
        geometry_gate_pass=geometry_gate_pass,
        arbitration_feasible=arbitration_feasible,
    )
    return report


def format_learning_trace(
    report: LearningReport,
    learner: PriorLearner,
    fp_learner: FingerprintPatchLearner,
    *,
    blocked_reason: str | None = None,
    score_decomposition: dict | None = None,
    geometry_valid: bool | None = None,
    geometry_gate_pass: bool | None = None,
    arbitration_feasible: bool | None = None,
) -> str:
    lines = [
        "=== Intervention Learning | S_final + cross-cluster + equilibrium arbitration (v1.3) ===",
        f"  legacy_store={report.store_size} | fp_store={report.fp_store_size} | "
        f"promoted={report.promoted_store_size} | observed={report.observations_recorded}",
    ]
    if report.fast_path_eligible and report.fast_path_fingerprint:
        lines.append(
            f"  FAST PATH: {report.fast_path_fingerprint} -> {report.recommended_patch} "
            f"S_arbitration={report.fast_path_s_final:.3f} (threshold={fp_learner.SCORE_THRESHOLD})"
        )
        lines.append(
            f"    raw={report.fast_path_score:.2f} legacy_effective={report.fast_path_effective_score} "
            f"elasticity={report.fast_path_elasticity:.2f}"
        )
        lines.append("  NOTE: unified scoring surface — suggestion only, explicit stack retains authority")
    elif blocked_reason:
        lines.append(f"  FAST PATH BLOCKED ({blocked_reason})")
        if report.fast_path_s_final is not None:
            lines.append(f"    S_final={report.fast_path_s_final:.3f} (need {fp_learner.SCORE_THRESHOLD})")
        elif report.fingerprint_recommendations and report.fingerprint_recommendations[0].s_final is not None:
            rec = report.fingerprint_recommendations[0]
            lines.append(f"    S_final={rec.s_final:.3f} (need {fp_learner.SCORE_THRESHOLD})")
    else:
        lines.append("  FAST PATH: not eligible — use explicit graph fallback")
    if score_decomposition:
        lines.append(f"  why_score: {score_decomposition}")
        lines.append(f"  surface={SCORING_SURFACE_VERSION} contract=ok")
    if geometry_valid is not None:
        geo_status = "ok" if geometry_valid else "VIOLATION"
        lines.append(f"  geometry_contract={geo_status}")
    if geometry_gate_pass is not None:
        gate_status = "PASS" if geometry_gate_pass else "BLOCKED"
        lines.append(f"  geometry_ci_gate={gate_status}")
    if arbitration_feasible is not None:
        arb_status = "FEASIBLE" if arbitration_feasible else "INFEASIBLE"
        lines.append(f"  constraint_arbitration={arb_status}")
    if report.fingerprint_recommendations:
        lines.append("  Fingerprint recommendations:")
        for rec in report.fingerprint_recommendations:
            tag = " [fast-path]" if rec.fast_path else f" [blocked:{blocked_reason}]" if blocked_reason else ""
            s_line = f" S_cal={rec.s_calibrated:.3f}" if rec.s_calibrated is not None else ""
            if rec.s_final is not None:
                s_line = f" S_raw={rec.s_final:.3f}{s_line}"
            lines.append(
                f"    {rec.fingerprint_id} -> {rec.patch_id} decayed={rec.score:.2f}{s_line} "
                f"attempts={rec.attempts} trust={rec.promoted}{tag}"
            )
    if report.predictions:
        lines.append("  Top predictions:")
        seen: set[str] = set()
        for p in report.predictions:
            key = f"{p.fingerprint_id}:{p.patch_id}"
            if key in seen:
                continue
            seen.add(key)
            fp_part = f" fp={p.fingerprint_id}" if p.fingerprint_id else ""
            lines.append(
                f"    {p.patch_id}: blend={p.blended_score:.2f} rate={p.success_rate:.2f} "
                f"conf={p.confidence:.2f} [{p.source}]{fp_part}"
            )
    return "\n".join(lines)


_default_learner: PriorLearner | None = None


def get_learner(store_path: Path | None = None) -> PriorLearner:
    global _default_learner
    if _default_learner is None:
        path = store_path or Path(".persona_ai") / "learned_priors.json"
        _default_learner = PriorLearner(path)
    return _default_learner


def enrich_with_learning(
    failure_report: FailureReport,
    session,
    learner: PriorLearner | None = None,
    fp_learner: FingerprintPatchLearner | None = None,
) -> FailureReport:
    learner = learner or get_learner()
    fp_learner = fp_learner or get_fp_learner()
    ingest_from_diagnostic_run(learner, failure_report, session, fp_learner)
    learning_report = build_learning_report(learner, failure_report, session, fp_learner)
    failure_report.intervention_learning = learning_report
    failure_report.debug_trace = failure_report.debug_trace + "\n\n" + learning_report.debug_trace
    return failure_report
