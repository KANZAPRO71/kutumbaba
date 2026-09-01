"""Regression delta dashboard — bug-centric run history and CLI."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from persona_ai.diagnostics.failure_fingerprint import (
    FingerprintRegistry,
    FingerprintReport,
)

if TYPE_CHECKING:
    from persona_ai.sim.smoke_openai import SmokeReport

DEFAULT_HISTORY_PATH = Path(".persona_ai/run_history.json")


@dataclass
class FingerprintLifecycle:
    new: list[str] = field(default_factory=list)
    known: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)

    @property
    def new_count(self) -> int:
        return len(self.new)

    @property
    def known_count(self) -> int:
        return len(self.known)

    @property
    def closed_count(self) -> int:
        return len(self.closed)

    @property
    def regression_count(self) -> int:
        return len(self.regressions)

    @property
    def total_active(self) -> int:
        return len(set(self.new + self.known))


@dataclass
class DerivedMetrics:
    stability_index: float
    fix_effectiveness: float
    novelty_rate: float

    def as_dict(self) -> dict[str, float]:
        return {
            "stability_index": self.stability_index,
            "fix_effectiveness": self.fix_effectiveness,
            "novelty_rate": self.novelty_rate,
        }


@dataclass
class RunSnapshot:
    run_id: str
    timestamp: str
    script_name: str
    adapter: str
    readiness: float
    readiness_grade: str
    grade: str
    contract_pass_rate: float
    structural_count: int
    fingerprints_present: list[str]
    fingerprints: dict[str, list[str]]
    derived: dict[str, float]
    recommended_patches: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunSnapshot:
        row = dict(data)
        row.setdefault("recommended_patches", {})
        return cls(**row)


def compute_derived_metrics(lifecycle: FingerprintLifecycle) -> DerivedMetrics:
    total = lifecycle.total_active + lifecycle.closed_count + lifecycle.regression_count
    total = max(total, 1)
    regressions = lifecycle.regression_count
    closed = lifecycle.closed_count
    stability = 1.0 - (regressions / total)
    fix_denom = max(closed + regressions, 1)
    fix_effectiveness = closed / fix_denom if closed + regressions > 0 else 1.0
    novelty = lifecycle.new_count / max(lifecycle.new_count + lifecycle.known_count, 1)
    return DerivedMetrics(
        stability_index=round(stability, 3),
        fix_effectiveness=round(fix_effectiveness, 3),
        novelty_rate=round(novelty, 3),
    )


def compute_lifecycle(
    present: list[str],
    *,
    previous_present: list[str] | None,
    registry: FingerprintRegistry,
) -> FingerprintLifecycle:
    present_set = set(present)
    prev_set = set(previous_present or [])

    new: list[str] = []
    known: list[str] = []
    for fp_id in sorted(present_set):
        if fp_id in registry.entries:
            known.append(fp_id)
        else:
            new.append(fp_id)

    closed = sorted(prev_set - present_set)
    regressions = sorted(fp for fp in present_set if registry.is_regression(fp))

    return FingerprintLifecycle(new=new, known=known, closed=closed, regressions=regressions)


def apply_lifecycle_side_effects(
    lifecycle: FingerprintLifecycle,
    registry: FingerprintRegistry,
) -> None:
    for fp_id in lifecycle.closed:
        registry.mark_closed(fp_id)
    for fp_id in lifecycle.regressions:
        if fp_id in registry.entries:
            registry.entries[fp_id].status = "open"


def lifecycle_to_dict(lifecycle: FingerprintLifecycle) -> dict[str, list[str]]:
    return {
        "new": lifecycle.new,
        "known": lifecycle.known,
        "closed": lifecycle.closed,
        "regressions": lifecycle.regressions,
    }


class RunHistoryStore:
    """Append-only run snapshots for regression tracking."""

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_HISTORY_PATH
        self.runs: list[RunSnapshot] = []
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.runs = [RunSnapshot.from_dict(item) for item in raw.get("runs", [])]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"runs": [asdict(r) for r in self.runs]}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def last_for_script(self, script_name: str) -> RunSnapshot | None:
        for snap in reversed(self.runs):
            if snap.script_name == script_name:
                return snap
        return None

    def filter_runs(self, script_name: str | None = None, limit: int | None = None) -> list[RunSnapshot]:
        runs = self.runs
        if script_name:
            runs = [r for r in runs if r.script_name == script_name]
        if limit is not None:
            runs = runs[-limit:]
        return runs

    def append(self, snapshot: RunSnapshot) -> None:
        self.runs.append(snapshot)


def build_snapshot(
    report: SmokeReport,
    *,
    run_id: str,
    lifecycle: FingerprintLifecycle,
    recommended_patches: dict[str, str] | None = None,
) -> RunSnapshot:
    fp_report: FingerprintReport | None = report.failure.fingerprints if report.failure else None
    present = list(fp_report.unique_ids) if fp_report else []
    derived = compute_derived_metrics(lifecycle)

    return RunSnapshot(
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        script_name=report.script_name,
        adapter=report.adapter,
        readiness=report.failure.readiness_score if report.failure else 100.0,
        readiness_grade=report.failure.readiness_grade if report.failure else "v2_ready",
        grade=report.smoke.grade,
        contract_pass_rate=round(report.smoke.contract_pass_rate, 4),
        structural_count=report.failure.structural_count if report.failure else 0,
        fingerprints_present=present,
        fingerprints=lifecycle_to_dict(lifecycle),
        derived=derived.as_dict(),
        recommended_patches=recommended_patches or {},
    )


def build_snapshot_from_smoke(
    report: SmokeReport,
    *,
    run_id: str,
    registry: FingerprintRegistry,
    history: RunHistoryStore,
) -> RunSnapshot:
    fp_report: FingerprintReport | None = report.failure.fingerprints if report.failure else None
    present = list(fp_report.unique_ids) if fp_report else []
    previous = history.last_for_script(report.script_name)
    lifecycle = compute_lifecycle(
        present,
        previous_present=previous.fingerprints_present if previous else None,
        registry=registry,
    )
    return build_snapshot(report, run_id=run_id, lifecycle=lifecycle)


def record_smoke_run(
    report: SmokeReport,
    *,
    run_id: str,
    registry: FingerprintRegistry | None = None,
    history: RunHistoryStore | None = None,
    persist: bool = True,
) -> RunSnapshot:
    """Persist registry + history snapshot from a smoke report."""
    from persona_ai.diagnostics.fingerprint_learning import get_fp_learner, ingest_lifecycle_outcomes
    from persona_ai.diagnostics.intervention_learning import extract_recommended_patches

    registry = registry or FingerprintRegistry()
    history = history or RunHistoryStore()
    fp_learner = get_fp_learner()

    fp_report = report.failure.fingerprints if report.failure else None
    present = list(fp_report.unique_ids) if fp_report else []
    previous = history.last_for_script(report.script_name)
    lifecycle = compute_lifecycle(
        present,
        previous_present=previous.fingerprints_present if previous else None,
        registry=registry,
    )

    if previous:
        ingest_lifecycle_outcomes(
            fp_learner,
            lifecycle=lifecycle,
            previous_recommended=previous.recommended_patches,
        )

    if fp_report and run_id:
        registry.record_run(fp_report, run_id=run_id, script_name=report.script_name)

    apply_lifecycle_side_effects(lifecycle, registry)
    recommended = extract_recommended_patches(report.failure) if report.failure else {}
    snapshot = build_snapshot(
        report,
        run_id=run_id,
        lifecycle=lifecycle,
        recommended_patches=recommended,
    )
    history.append(snapshot)

    if persist:
        registry.save()
        history.save()

    return snapshot


def _fmt_delta(current: float, previous: float | None, *, pct: bool = False) -> str:
    if previous is None:
        return f"{current:.2f}" if not pct else f"{current:.0%}"
    delta = current - previous
    sign = "+" if delta >= 0 else ""
    if pct:
        return f"{previous:.0%} -> {current:.0%} ({sign}{delta:.0%})"
    return f"{previous:.0f} -> {current:.0f} ({sign}{delta:.0f})"


def _fp_label(fp_id: str, registry: FingerprintRegistry) -> str:
    entry = registry.entries.get(fp_id)
    if not entry:
        return fp_id
    ctx = entry.display.split("|ctx=")
    ctx_part = ctx[1].split("|")[0] if len(ctx) > 1 else "?"
    return f"{fp_id} ({ctx_part})"


def format_run_delta(
    current: RunSnapshot,
    previous: RunSnapshot | None,
    registry: FingerprintRegistry,
) -> str:
    lines = [
        "=== RUN DELTA ===",
        f"script: {current.script_name} | run: {current.run_id}",
        f"readiness: {_fmt_delta(current.readiness, previous.readiness if previous else None)}",
        f"contract: {_fmt_delta(current.contract_pass_rate, previous.contract_pass_rate if previous else None, pct=True)}",
        f"grade: {previous.grade if previous else '-'} -> {current.grade}",
        "",
        "fingerprints:",
        f"  new: {len(current.fingerprints['new'])}",
        f"  known: {len(current.fingerprints['known'])}",
        f"  closed: {len(current.fingerprints['closed'])}",
        f"  regressions: {len(current.fingerprints['regressions'])}",
    ]
    fp = current.fingerprints
    if fp["new"]:
        lines.append("  new ids: " + ", ".join(fp["new"]))
    if fp["closed"]:
        lines.append("  closed ids: " + ", ".join(_fp_label(i, registry) for i in fp["closed"]))
    if fp["regressions"]:
        lines.append("")
        lines.append("REGRESSION:")
        for fp_id in fp["regressions"]:
            entry = registry.entries.get(fp_id)
            closed_run = previous.run_id if previous else "?"
            lines.append(f"  {_fp_label(fp_id, registry)}")
            lines.append(f"    closed before | reappeared in {current.run_id} (prev snapshot: {closed_run})")
            if entry:
                lines.append(f"    semantic: {entry.semantic_key}")
    return "\n".join(lines)


def format_system_health(runs: list[RunSnapshot]) -> str:
    if not runs:
        return "=== System Health | no runs recorded ==="
    lines = ["=== System Health (recent runs) ===", "run_id                  | grade | readiness | contract | structural"]
    for r in runs[-8:]:
        lines.append(
            f"{r.run_id[:22]:22s} | {r.grade:5s} | {r.readiness:9.0f} | {r.contract_pass_rate:7.0%} | {r.structural_count}"
        )
    return "\n".join(lines)


def format_lifecycle_bars(runs: list[RunSnapshot]) -> str:
    if not runs:
        return "=== Fingerprint Lifecycle | no data ==="
    lines = ["=== Fingerprint Lifecycle (per run) ===", "run_id                  | new | known | closed | regr"]
    for r in runs[-8:]:
        fp = r.fingerprints
        lines.append(
            f"{r.run_id[:22]:22s} | {len(fp['new']):3d} | {len(fp['known']):5d} | "
            f"{len(fp['closed']):6d} | {len(fp['regressions']):4d}"
        )
    return "\n".join(lines)


def format_top_recurring(registry: FingerprintRegistry, limit: int = 5) -> str:
    ranked = sorted(registry.entries.values(), key=lambda e: -e.occurrence_count)
    if not ranked:
        return "=== Top Recurring | none ==="
    lines = ["=== Top Recurring Fingerprints ==="]
    for entry in ranked[:limit]:
        status = entry.status
        lines.append(
            f"  {entry.fingerprint_id} x{entry.occurrence_count} [{status}] last={entry.last_seen_at[:10]}"
        )
        lines.append(f"    {entry.semantic_key}")
    return "\n".join(lines)


def format_patch_leaderboard(limit_per_fp: int = 3) -> str:
    from persona_ai.diagnostics.fingerprint_learning import get_fp_learner

    fp_learner = get_fp_learner()
    if fp_learner.store_size == 0:
        return "=== Patch Leaderboard | no fingerprint learning data ==="

    lines = ["=== Patch Leaderboard (per fingerprint) ==="]
    for fp_id in sorted(fp_learner._store.keys()):
        board = fp_learner.leaderboard(fp_id, limit=limit_per_fp)
        if not board:
            continue
        lines.append(f"  {fp_id}:")
        for row in board:
            if row.attempts == 0:
                continue
            lines.append(
                f"    {row.patch_id} -> raw {row.raw_score:.2f} | decayed {row.decayed_score:.2f} "
                f"(eff={row.effective_attempts:.2f} df={row.decay_factor:.2f})"
            )
    return "\n".join(lines) if len(lines) > 1 else "=== Patch Leaderboard | no attempts recorded ==="


def format_derived_kpi(snapshot: RunSnapshot) -> str:
    d = snapshot.derived
    return "\n".join([
        "=== Derived KPIs (latest run) ===",
        f"  stability_index:    {d['stability_index']:.3f}  (1 - regressions/total)",
        f"  fix_effectiveness:  {d['fix_effectiveness']:.3f}  (closed / (closed + regressions))",
        f"  novelty_rate:       {d['novelty_rate']:.3f}  (new / (new + known))",
    ])


def format_dashboard(
    history: RunHistoryStore,
    registry: FingerprintRegistry,
    *,
    script_name: str | None = None,
    limit: int = 10,
) -> str:
    runs = history.filter_runs(script_name=script_name, limit=limit)
    if not runs:
        return "No run history recorded. Re-run smoke with --record:\n  python -m persona_ai.sim.smoke_openai semantic_chaos --record"

    current = runs[-1]
    previous = runs[-2] if len(runs) >= 2 else None

    sections = [
        format_run_delta(current, previous, registry),
        "",
        format_system_health(runs),
        "",
        format_lifecycle_bars(runs),
        "",
        format_derived_kpi(current),
        "",
        format_top_recurring(registry),
        "",
        format_patch_leaderboard(),
    ]
    return "\n".join(sections)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persona AI regression delta dashboard (CLI)")
    parser.add_argument("--script", default=None, help="Filter by script name (e.g. semantic_chaos)")
    parser.add_argument("--last", type=int, default=10, help="Number of recent runs to include")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY_PATH, help="Run history JSON path")
    parser.add_argument("--registry", type=Path, default=FingerprintRegistry.DEFAULT_PATH, help="Fingerprint registry path")
    parser.add_argument("--shadow", action="store_true", help="Include shadow comparison (sim vs production)")
    parser.add_argument("--promote", action="store_true", help="Include promotion gate evaluation")
    parser.add_argument("--persist-promoted", action="store_true", help="With --promote, write promoted_learnings.json")
    parser.add_argument("--monitor-promoted", action="store_true", help="Run false promotion detector on promoted set")
    parser.add_argument("--persist-lifecycle", action="store_true", help="With --monitor-promoted, apply lifecycle updates")
    parser.add_argument("--drift", action="store_true", help="Run shadow drift alerts on promoted set")
    parser.add_argument("--persist-drift", action="store_true", help="With --drift, append drift snapshot")
    parser.add_argument("--trust-decisions", action="store_true", help="Run drift-to-demotion decision engine")
    parser.add_argument("--persist-decisions", action="store_true", help="With --trust-decisions, append trust_decisions.json")
    parser.add_argument(
        "--apply-quarantine",
        action="store_true",
        help="With --trust-decisions, apply QUARANTINE_REVIEW to promoted store",
    )
    parser.add_argument("--explainability", action="store_true", help="Include explainability contract dashboard")
    parser.add_argument("--geometry", action="store_true", help="Include S_final geometry contract panel")
    parser.add_argument(
        "--geometry-gate",
        action="store_true",
        help="Include Geometry CI Gate (coupled separation invariants)",
    )
    parser.add_argument(
        "--manifold-regime",
        action="store_true",
        help="Include manifold regime timeline (I0-I6 invariance classifier)",
    )
    parser.add_argument(
        "--runtime-soft",
        action="store_true",
        help="Include runtime SOFT observer stream",
    )
    parser.add_argument(
        "--manifold-dynamics",
        action="store_true",
        help="Include Phase D Markov dynamics (transition matrix, drift, half-life)",
    )
    parser.add_argument(
        "--forecast-matrix",
        action="store_true",
        help="Include regime×horizon forecast verification matrix (D.3.1 evidence panel)",
    )
    args = parser.parse_args(argv)

    history = RunHistoryStore(args.history)
    registry = FingerprintRegistry(args.registry)
    runs = history.filter_runs(script_name=args.script, limit=args.last)

    if args.json:
        payload = {
            "runs": [asdict(r) for r in runs],
            "registry_size": len(registry.entries),
        }
        if args.shadow or args.promote:
            from persona_ai.diagnostics.shadow_comparator import ShadowComparator

            payload["shadow"] = ShadowComparator().build_report().to_dict()
        if args.promote:
            from persona_ai.diagnostics.promotion_gate import PromotionGate, PromotedLearningStore

            gate = PromotionGate(PromotedLearningStore())
            payload["promotion"] = gate.run(persist=args.persist_promoted).to_dict()
        if args.monitor_promoted:
            from persona_ai.diagnostics.false_promotion_detector import FalsePromotionDetector
            from persona_ai.diagnostics.promotion_gate import PromotedLearningStore

            detector = FalsePromotionDetector(PromotedLearningStore())
            payload["false_promotion"] = detector.run(persist=args.persist_lifecycle).to_dict()
        if args.drift:
            from persona_ai.diagnostics.promotion_gate import PromotedLearningStore
            from persona_ai.diagnostics.shadow_drift_alerts import ShadowDriftMonitor

            drift = ShadowDriftMonitor(PromotedLearningStore()).run(persist=args.persist_drift)
            payload["drift"] = drift.to_dict()
        if args.trust_decisions:
            from persona_ai.diagnostics.promotion_gate import PromotedLearningStore
            from persona_ai.diagnostics.trust_decision_engine import TrustDecisionEngine

            decisions = TrustDecisionEngine(PromotedLearningStore()).run(
                persist=args.persist_decisions,
                apply_quarantine=args.apply_quarantine,
            )
            payload["trust_decisions"] = decisions.to_dict()
        if args.explainability:
            from persona_ai.diagnostics.explainability_dashboard import ExplainabilityDashboard

            payload["explainability"] = ExplainabilityDashboard().build_report().to_dict()
        if args.geometry:
            from persona_ai.diagnostics.geometry_contract import format_geometry_verdict, verify_geometry_contract
            from persona_ai.diagnostics.explainability_dashboard import ExplainabilityTelemetryStore

            samples = []
            for snap in ExplainabilityTelemetryStore().snapshots[-1:]:
                for rec in snap.records:
                    from persona_ai.diagnostics.geometry_contract import GeometrySample

                    samples.append(
                        GeometrySample(
                            fp_id=rec.fp_id,
                            patch_id=rec.patch_id,
                            s_final_raw=rec.s_final,
                        )
                    )
            gv = verify_geometry_contract(samples)
            payload["geometry"] = gv.to_dict()
        if args.geometry_gate:
            from persona_ai.diagnostics.explainability_dashboard import ExplainabilityTelemetryStore
            from persona_ai.diagnostics.geometry_ci_gate import (
                CoupledGeometrySample,
                format_geometry_gate_verdict,
                run_ci_check,
            )

            coupled: list[CoupledGeometrySample] = []
            for snap in ExplainabilityTelemetryStore().snapshots[-5:]:
                for rec in snap.records:
                    coupled.append(
                        CoupledGeometrySample(
                            fp_id=rec.fp_id,
                            patch_id=rec.patch_id,
                            s_final_raw=rec.s_final,
                        )
                    )
            gate = run_ci_check(coupled, enforce_regression=False)
            payload["geometry_gate"] = gate.to_dict()
        if args.manifold_regime:
            from persona_ai.diagnostics.arbitration_telemetry import ArbitrationTelemetryStore
            from persona_ai.diagnostics.invariance_classifier import build_regime_timeline

            store = ArbitrationTelemetryStore()
            ci_snaps = [s for s in store.snapshots if s.identity.source == "ci"]
            payload["manifold_regime"] = [
                entry.to_dict() for entry in build_regime_timeline(ci_snaps[-20:])
            ]
        if args.runtime_soft:
            from persona_ai.diagnostics.runtime_soft_observer import RuntimeSoftTelemetryStore

            payload["runtime_soft"] = [
                s.to_dict() for s in RuntimeSoftTelemetryStore().snapshots[-20:]
            ]
        if args.manifold_dynamics:
            from persona_ai.diagnostics.manifold_dynamics import build_manifold_dynamics_report
            from persona_ai.diagnostics.markov_validation import build_markov_validation_report

            payload["manifold_dynamics"] = build_manifold_dynamics_report().to_dict()
            payload["markov_validation"] = build_markov_validation_report(update_baseline=False).to_dict()
            from persona_ai.diagnostics.metastability import build_metastability_report

            payload["metastability"] = build_metastability_report(update_baseline=False).to_dict()
            from persona_ai.diagnostics.regime_forecast import build_regime_forecast_report

            payload["regime_forecast"] = build_regime_forecast_report().to_dict()
            from persona_ai.diagnostics.forecast_verification import build_forecast_verification_report

            payload["forecast_verification"] = build_forecast_verification_report().to_dict()
        if args.forecast_matrix:
            from persona_ai.diagnostics.forecast_verification import build_forecast_verification_report

            payload["forecast_matrix"] = build_forecast_verification_report().matrix.to_dict()
        print(json.dumps(payload, indent=2))
        return 0

    output = format_dashboard(history, registry, script_name=args.script, limit=args.last)
    if args.shadow:
        from persona_ai.diagnostics.shadow_comparator import ShadowComparator, format_shadow_report

        output = output + "\n\n" + format_shadow_report(ShadowComparator().build_report())
    if args.promote:
        from persona_ai.diagnostics.promotion_gate import PromotionGate, PromotedLearningStore

        promo = PromotionGate(PromotedLearningStore()).run(persist=args.persist_promoted)
        output = output + "\n\n" + promo.debug_trace
    if args.monitor_promoted:
        from persona_ai.diagnostics.false_promotion_detector import FalsePromotionDetector
        from persona_ai.diagnostics.promotion_gate import PromotedLearningStore

        survival = FalsePromotionDetector(PromotedLearningStore()).run(persist=args.persist_lifecycle)
        output = output + "\n\n" + survival.debug_trace
    if args.drift:
        from persona_ai.diagnostics.promotion_gate import PromotedLearningStore
        from persona_ai.diagnostics.shadow_drift_alerts import ShadowDriftMonitor

        drift = ShadowDriftMonitor(PromotedLearningStore()).run(persist=args.persist_drift)
        output = output + "\n\n" + drift.debug_trace
    if args.trust_decisions:
        from persona_ai.diagnostics.promotion_gate import PromotedLearningStore
        from persona_ai.diagnostics.trust_decision_engine import TrustDecisionEngine

        decisions = TrustDecisionEngine(PromotedLearningStore()).run(
            persist=args.persist_decisions,
            apply_quarantine=args.apply_quarantine,
        )
        output = output + "\n\n" + decisions.debug_trace
    if args.explainability:
        from persona_ai.diagnostics.explainability_dashboard import ExplainabilityDashboard

        expl = ExplainabilityDashboard().build_report()
        output = output + "\n\n" + expl.debug_trace
    if args.geometry:
        from persona_ai.diagnostics.explainability_dashboard import ExplainabilityTelemetryStore
        from persona_ai.diagnostics.geometry_contract import GeometrySample, format_geometry_verdict, verify_geometry_contract

        samples = []
        for snap in ExplainabilityTelemetryStore().snapshots[-5:]:
            for rec in snap.records:
                samples.append(
                    GeometrySample(fp_id=rec.fp_id, patch_id=rec.patch_id, s_final_raw=rec.s_final)
                )
        output = output + "\n\n" + format_geometry_verdict(verify_geometry_contract(samples))
    if args.geometry_gate:
        from persona_ai.diagnostics.explainability_dashboard import ExplainabilityTelemetryStore
        from persona_ai.diagnostics.geometry_ci_gate import (
            CoupledGeometrySample,
            format_geometry_gate_verdict,
            run_ci_check,
        )

        coupled = []
        for snap in ExplainabilityTelemetryStore().snapshots[-5:]:
            for rec in snap.records:
                coupled.append(
                    CoupledGeometrySample(
                        fp_id=rec.fp_id,
                        patch_id=rec.patch_id,
                        s_final_raw=rec.s_final,
                    )
                )
        output = output + "\n\n" + format_geometry_gate_verdict(run_ci_check(coupled, enforce_regression=False))
    if args.manifold_regime:
        from persona_ai.diagnostics.arbitration_telemetry import ArbitrationTelemetryStore
        from persona_ai.diagnostics.invariance_classifier import (
            build_regime_timeline,
            format_manifold_regime_timeline,
        )

        store = ArbitrationTelemetryStore()
        ci_snaps = [s for s in store.snapshots if s.identity.source == "ci"]
        output = output + "\n\n" + format_manifold_regime_timeline(
            build_regime_timeline(ci_snaps[-20:])
        )
    if args.runtime_soft:
        from persona_ai.diagnostics.runtime_soft_observer import (
            RuntimeSoftTelemetryStore,
            format_runtime_observer_report,
        )

        output = output + "\n\n" + format_runtime_observer_report(RuntimeSoftTelemetryStore())
    if args.manifold_dynamics:
        from persona_ai.diagnostics.manifold_dynamics import (
            build_manifold_dynamics_report,
            format_manifold_dynamics_report,
        )
        from persona_ai.diagnostics.markov_validation import (
            build_markov_validation_report,
            format_markov_validation_report,
        )
        from persona_ai.diagnostics.metastability import (
            build_metastability_report,
            format_metastability_report,
        )

        output = output + "\n\n" + format_manifold_dynamics_report(build_manifold_dynamics_report())
        output = output + "\n\n" + format_markov_validation_report(
            build_markov_validation_report(update_baseline=False)
        )
        output = output + "\n\n" + format_metastability_report(
            build_metastability_report(update_baseline=False)
        )
        from persona_ai.diagnostics.regime_forecast import (
            build_regime_forecast_report,
            format_regime_forecast_report,
        )

        output = output + "\n\n" + format_regime_forecast_report(build_regime_forecast_report())
        from persona_ai.diagnostics.forecast_verification import (
            build_forecast_verification_report,
            format_forecast_verification_report,
        )

        output = output + "\n\n" + format_forecast_verification_report(
            build_forecast_verification_report()
        )
    if args.forecast_matrix and not args.manifold_dynamics:
        from persona_ai.diagnostics.forecast_verification import (
            build_forecast_verification_report,
            format_forecast_verification_matrix,
        )

        output = output + "\n\n" + format_forecast_verification_matrix(
            build_forecast_verification_report().matrix
        )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
