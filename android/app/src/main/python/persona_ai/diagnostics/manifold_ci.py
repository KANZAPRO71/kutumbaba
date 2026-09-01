"""Manifold CI v1 — axiom lock for constrained trust control stack.

Enforces: no commit/deploy is valid unless manifold state is valid.

Pipeline order:
  1. geometry_ci_gate
  2. constraint_arbitration (feasibility)
  3. explainability_contract
  4. cross_cluster_calibration (sanity)
  5. shadow_drift (regression warning)

Exit codes:
  0  PASS
  1  geometry gate BLOCKED
  2  geometry regression vs baseline
  3  arbitration INFEASIBLE
  4  scalar / explainability violation
  5  cross-cluster sanity failure
  10 drift monotonic warning (--strict-drift elevates to failure)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Literal

from persona_ai.diagnostics.constraint_arbitration import (
    arbitrate_from_calibration,
    format_arbitration_trace,
)
from persona_ai.diagnostics.cross_cluster_calibration import (
    calibrate_cross_cluster_batch,
    semantic_cluster_key,
)
from persona_ai.diagnostics.explainability_contract import (
    RECONSTRUCTION_EPSILON,
    format_verdict,
    verify_explainability_contract,
)
from persona_ai.diagnostics.fast_path_controller import compute_S_final
from persona_ai.diagnostics.geometry_ci_gate import (
    format_geometry_gate_verdict,
    run_ci_check,
    samples_from_cross_results,
)
from persona_ai.diagnostics.shadow_drift_alerts import DEFAULT_ALERTS_PATH
from persona_ai.diagnostics.surface_calibration import MAX_CALIBRATION_DELTA

MANIFOLD_CI_VERSION = "v1"

CANONICAL_SEMANTIC = {
    "fp_a": "FP::INTENT::CTX::ROOT",
    "fp_b": "FP::INCOMPLETE::DEFER::ROOT",
    "fp_c": "FP::CONTEXT::SHIFT::ROOT",
}


class ManifoldExit(IntEnum):
    PASS = 0
    GEOMETRY_BLOCKED = 1
    GEOMETRY_REGRESSION = 2
    ARBITRATION_INFEASIBLE = 3
    SCALAR_VIOLATION = 4
    CROSS_CLUSTER_SANITY = 5
    DRIFT_WARNING = 10


StepStatus = Literal["PASS", "BLOCKED", "INFEASIBLE", "VIOLATION", "WARN", "SKIP"]


@dataclass
class CIStepResult:
    step: str
    status: StepStatus
    exit_code: int
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanonicalFixture:
    patch_ids: list[str]
    semantic_by_fp: dict[str, str]
    cross_results: list[Any]
    calibrated: list[Any]
    geometry_gate: Any
    arbitration: Any
    decomps: list[Any]


def build_canonical_fixture() -> CanonicalFixture:
    """Shared reference batch for reproducible CI checks."""
    items = [
        (
            "fp_a",
            "p1",
            compute_S_final(
                raw_score=0.52,
                learned_score=0.48,
                elasticity_weight=1.0,
                decay_factor=1.0,
                trust_state="active",
            ),
        ),
        (
            "fp_b",
            "p2",
            compute_S_final(
                raw_score=0.38,
                learned_score=0.42,
                elasticity_weight=1.0,
                decay_factor=1.0,
                trust_state="active",
            ),
        ),
        (
            "fp_c",
            "p3",
            compute_S_final(
                raw_score=0.71,
                learned_score=0.68,
                elasticity_weight=0.95,
                decay_factor=1.0,
                trust_state="active",
            ),
        ),
    ]
    calibrated, _, cross, gate = calibrate_cross_cluster_batch(
        items,
        semantic_by_fp=CANONICAL_SEMANTIC,
        persist=False,
        enforce_regression=False,
    )
    arbitration = arbitrate_from_calibration(
        calibrated,
        cross,
        ["p1", "p2", "p3"],
        gate_verdict=gate,
    )
    fixture = CanonicalFixture(
        patch_ids=["p1", "p2", "p3"],
        semantic_by_fp=CANONICAL_SEMANTIC,
        cross_results=cross,
        calibrated=calibrated,
        geometry_gate=gate,
        arbitration=arbitration,
        decomps=[item[2] for item in items],
    )
    return fixture


def check_geometry_ci_gate(fixture: CanonicalFixture | None = None) -> CIStepResult:
    fixture = fixture or build_canonical_fixture()
    gate = fixture.geometry_gate
    if gate is None:
        samples = samples_from_cross_results(fixture.cross_results, fixture.patch_ids)
        gate = run_ci_check(samples, enforce_regression=False)

    if gate.pass_gate:
        return CIStepResult(
            step="geometry_ci_gate",
            status="PASS",
            exit_code=ManifoldExit.PASS,
            message="geometry CI gate PASS",
            detail=gate.to_dict(),
        )
    if gate.regression_detected:
        return CIStepResult(
            step="geometry_ci_gate",
            status="BLOCKED",
            exit_code=ManifoldExit.GEOMETRY_REGRESSION,
            message="geometry regression vs baseline",
            detail=gate.to_dict(),
        )
    return CIStepResult(
        step="geometry_ci_gate",
        status="BLOCKED",
        exit_code=ManifoldExit.GEOMETRY_BLOCKED,
        message="geometry CI gate BLOCKED",
        detail=gate.to_dict(),
    )


def check_constraint_arbitration(fixture: CanonicalFixture | None = None) -> CIStepResult:
    fixture = fixture or build_canonical_fixture()
    verdict = fixture.arbitration
    if verdict.batch_feasible and verdict.gate_admitted:
        return CIStepResult(
            step="constraint_arbitration",
            status="PASS",
            exit_code=ManifoldExit.PASS,
            message="constraint arbitration FEASIBLE",
            detail=verdict.to_dict(),
        )
    if not verdict.gate_admitted:
        return CIStepResult(
            step="constraint_arbitration",
            status="BLOCKED",
            exit_code=ManifoldExit.GEOMETRY_BLOCKED,
            message="arbitration rejected — gate not admitted",
            detail=verdict.to_dict(),
        )
    return CIStepResult(
        step="constraint_arbitration",
        status="INFEASIBLE",
        exit_code=ManifoldExit.ARBITRATION_INFEASIBLE,
        message="constraint arbitration INFEASIBLE",
        detail=verdict.to_dict(),
    )


def check_explainability_contract(fixture: CanonicalFixture | None = None) -> CIStepResult:
    fixture = fixture or build_canonical_fixture()
    violations: list[str] = []
    max_delta = 0.0
    for decomp in fixture.decomps:
        verdict = verify_explainability_contract(decomp)
        if not verdict.valid:
            violations.extend(v.code for v in verdict.violations)
        if verdict.reconstruction_delta is not None:
            max_delta = max(max_delta, verdict.reconstruction_delta)

    if max_delta > RECONSTRUCTION_EPSILON:
        violations.append(f"reconstruction_delta>{RECONSTRUCTION_EPSILON}")

    if violations:
        return CIStepResult(
            step="explainability_contract",
            status="VIOLATION",
            exit_code=ManifoldExit.SCALAR_VIOLATION,
            message=f"explainability violations: {', '.join(sorted(set(violations)))}",
            detail={"max_reconstruction_delta": max_delta, "epsilon": RECONSTRUCTION_EPSILON},
        )
    return CIStepResult(
        step="explainability_contract",
        status="PASS",
        exit_code=ManifoldExit.PASS,
        message=f"explainability contract ok (max_delta={max_delta:.6f})",
        detail={"max_reconstruction_delta": max_delta, "epsilon": RECONSTRUCTION_EPSILON},
    )


def check_cross_cluster_sanity(fixture: CanonicalFixture | None = None) -> CIStepResult:
    fixture = fixture or build_canonical_fixture()
    issues: list[str] = []

    clusters = {cr.semantic_cluster for cr in fixture.cross_results}
    if len(clusters) < 2:
        issues.append("semantic_cluster_collapse")

    for cross in fixture.cross_results:
        if abs(cross.calibration_delta) > MAX_CALIBRATION_DELTA + 1e-6:
            issues.append(f"delta_exceeded:{cross.fp_id}")
        key = semantic_cluster_key(fixture.semantic_by_fp.get(cross.fp_id, ""))
        if key != cross.semantic_cluster:
            issues.append(f"cluster_key_mismatch:{cross.fp_id}")

    raw = [cr.s_final_raw for cr in fixture.cross_results]
    cal = [cr.s_calibrated for cr in fixture.cross_results]
    if len(raw) >= 2 and cal[0] > cal[1] and raw[0] < raw[1]:
        issues.append("rank_inversion")

    if fixture.geometry_gate and not fixture.geometry_gate.pass_gate:
        issues.append("geometry_gate_failed")

    if issues:
        return CIStepResult(
            step="cross_cluster_calibration",
            status="VIOLATION",
            exit_code=ManifoldExit.CROSS_CLUSTER_SANITY,
            message=f"cross-cluster sanity failed: {', '.join(issues)}",
            detail={"issues": issues},
        )
    return CIStepResult(
        step="cross_cluster_calibration",
        status="PASS",
        exit_code=ManifoldExit.PASS,
        message="cross-cluster calibration sanity ok",
        detail={"cluster_count": len(clusters), "sample_count": len(fixture.cross_results)},
    )


def check_shadow_drift_regression(
    *,
    alerts_path: Path | None = None,
    min_snapshots: int = 3,
) -> CIStepResult:
    """Warn when at_risk alert count rises monotonically (non-blocking by default)."""
    path = alerts_path or DEFAULT_ALERTS_PATH
    if not path.exists():
        return CIStepResult(
            step="shadow_drift",
            status="SKIP",
            exit_code=ManifoldExit.PASS,
            message="no drift alert history — skip regression check",
            detail={"path": str(path)},
        )

    raw = json.loads(path.read_text(encoding="utf-8"))
    snapshots = raw.get("snapshots", [])
    if len(snapshots) < min_snapshots:
        return CIStepResult(
            step="shadow_drift",
            status="SKIP",
            exit_code=ManifoldExit.PASS,
            message=f"insufficient drift history ({len(snapshots)}<{min_snapshots})",
            detail={"snapshot_count": len(snapshots)},
        )

    counts = [
        sum(1 for alert in snap.get("alerts", []) if alert.get("alert_status") == "at_risk")
        for snap in snapshots[-5:]
    ]
    monotonic_rise = all(counts[i] <= counts[i + 1] for i in range(len(counts) - 1))
    rising = monotonic_rise and counts[-1] > counts[0]

    if rising:
        return CIStepResult(
            step="shadow_drift",
            status="WARN",
            exit_code=ManifoldExit.DRIFT_WARNING,
            message=f"monotonic at_risk trend detected: {counts}",
            detail={"at_risk_counts": counts, "monotonic_rise": True},
        )
    return CIStepResult(
        step="shadow_drift",
        status="PASS",
        exit_code=ManifoldExit.PASS,
        message=f"drift regression check ok (at_risk={counts})",
        detail={"at_risk_counts": counts},
    )


@dataclass
class ManifoldCIReport:
    version: str
    passed: bool
    exit_code: int
    steps: list[CIStepResult]
    warnings: list[CIStepResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifold_ci_version": self.version,
            "passed": self.passed,
            "exit_code": self.exit_code,
            "steps": [step.to_dict() for step in self.steps],
            "warnings": [step.to_dict() for step in self.warnings],
        }


def run_manifold_ci(
    *,
    strict_drift: bool = False,
    enforce_regression: bool = False,
) -> ManifoldCIReport:
    """Run full manifold CI pipeline on canonical fixture."""
    fixture = build_canonical_fixture()

    if enforce_regression:
        samples = samples_from_cross_results(fixture.cross_results, fixture.patch_ids)
        fixture.geometry_gate = run_ci_check(samples, enforce_regression=True)

    steps = [
        check_geometry_ci_gate(fixture),
        check_constraint_arbitration(fixture),
        check_explainability_contract(fixture),
        check_cross_cluster_sanity(fixture),
    ]

    drift = check_shadow_drift_regression()
    warnings: list[CIStepResult] = []
    if drift.status == "WARN":
        warnings.append(drift)
        if strict_drift:
            steps.append(drift)
        else:
            steps.append(
                CIStepResult(
                    step=drift.step,
                    status="PASS",
                    exit_code=ManifoldExit.PASS,
                    message=f"{drift.message} (warning only)",
                    detail=drift.detail,
                )
            )
    else:
        steps.append(drift)

    blocking = [step for step in steps if step.status in ("BLOCKED", "INFEASIBLE", "VIOLATION")]
    exit_code = ManifoldExit.PASS
    if blocking:
        exit_code = ManifoldExit(blocking[0].exit_code)

    return ManifoldCIReport(
        version=MANIFOLD_CI_VERSION,
        passed=len(blocking) == 0,
        exit_code=int(exit_code),
        steps=steps,
        warnings=warnings,
    )


def check_markov_validation_diagnostic(
    *,
    update_baseline: bool = True,
    report: Any | None = None,
) -> CIStepResult:
    """Phase D.1 — diagnostics only; never blocks CI."""
    from persona_ai.diagnostics.markov_validation import MarkovValidationReport, build_markov_validation_report

    markov_report: MarkovValidationReport = report or build_markov_validation_report(
        update_baseline=update_baseline
    )
    if markov_report.commit_blocks == 0 and not markov_report.markov_order.sufficient_samples:
        return CIStepResult(
            step="markov_validation",
            status="SKIP",
            exit_code=ManifoldExit.PASS,
            message="insufficient event history for Markov validation",
            detail=markov_report.to_dict(),
        )

    order = markov_report.markov_order
    stationary = markov_report.stationarity
    kl = markov_report.kl_divergence
    message = (
        f"order1_valid={order.order1_valid} "
        f"kernel_stable={stationary.kernel_stable} "
        f"KL={kl.kl_global:.4f} ({stationary.classification})"
    )
    return CIStepResult(
        step="markov_validation",
        status="PASS",
        exit_code=ManifoldExit.PASS,
        message=message,
        detail=markov_report.to_dict(),
    )


def run_manifold_ci_with_validation(
    *,
    strict_drift: bool = False,
    enforce_regression: bool = False,
    record_validation_baseline: bool = True,
) -> ManifoldCIReport:
    """Full CI pipeline including Phase D.1 diagnostic step."""
    report = run_manifold_ci(strict_drift=strict_drift, enforce_regression=enforce_regression)
    validation = check_markov_validation_diagnostic(update_baseline=record_validation_baseline)
    report.steps.append(validation)
    return report


def record_ci_phase_snapshot(
    report: ManifoldCIReport,
    fixture: CanonicalFixture | None = None,
    *,
    persist: bool = True,
) -> Any:
    """Emit HARD-frame CI lattice point to phase-space telemetry."""
    from persona_ai.diagnostics.arbitration_telemetry import ArbitrationTelemetryStore

    fixture = fixture or build_canonical_fixture()
    violation_codes: list[str] = []
    for step in report.steps:
        if step.status in ("BLOCKED", "INFEASIBLE", "VIOLATION"):
            violation_codes.append(f"{step.step}:{step.status}")

    store = ArbitrationTelemetryStore()
    return store.record_ci_lattice(
        fixture,
        ci_exit_code=report.exit_code,
        violation_codes=violation_codes,
        persist=persist,
    )


def format_manifold_ci_report(report: ManifoldCIReport) -> str:
    status = "PASS" if report.passed else "FAIL"
    lines = [
        f"=== Manifold CI | {report.version} ===",
        f"  status: {status} | exit={report.exit_code}",
        "",
    ]
    for step in report.steps:
        icon = {
            "PASS": "OK",
            "SKIP": "--",
            "WARN": "!!",
            "BLOCKED": "XX",
            "INFEASIBLE": "XX",
            "VIOLATION": "XX",
        }.get(step.status, "??")
        lines.append(f"  [{icon}] {step.step}: {step.message} (exit={step.exit_code})")
    if report.warnings:
        lines.append("")
        lines.append("  Warnings (non-blocking):")
        for warning in report.warnings:
            lines.append(f"    !! {warning.step}: {warning.message}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Manifold CI — axiom lock for trust control stack")
    parser.add_argument("--check", action="store_true", help="Run full manifold CI pipeline")
    parser.add_argument("--strict-drift", action="store_true", help="Fail on drift monotonic warning")
    parser.add_argument("--enforce-regression", action="store_true", help="Enable geometry baseline regression")
    parser.add_argument("--record-telemetry", action="store_true", help="Record CI lattice phase snapshot")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="Include sub-module traces")
    args = parser.parse_args(argv)

    fixture = build_canonical_fixture()
    report = run_manifold_ci(
        strict_drift=args.strict_drift,
        enforce_regression=args.enforce_regression,
    )

    if args.record_telemetry or args.check:
        snapshot = record_ci_phase_snapshot(report, fixture, persist=True)
        from persona_ai.diagnostics.markov_validation import (
            build_markov_validation_report,
            format_markov_validation_report,
        )

        markov_report = build_markov_validation_report(update_baseline=args.record_telemetry)
        report.steps.append(
            check_markov_validation_diagnostic(
                update_baseline=False,
                report=markov_report,
            )
        )
        from persona_ai.diagnostics.metastability import (
            build_metastability_report,
            format_metastability_report,
        )

        metastability_report = build_metastability_report(update_baseline=args.record_telemetry)
        report.steps.append(
            CIStepResult(
                step="metastability",
                status="PASS",
                exit_code=ManifoldExit.PASS,
                message=(
                    f"gap={metastability_report.spectral_gap.spectral_gap:.4f} "
                    f"boundary_warning={metastability_report.boundary_warning.warning_active}"
                ),
                detail=metastability_report.to_dict(),
            )
        )
        from persona_ai.diagnostics.regime_forecast import (
            build_regime_forecast_report,
            format_regime_forecast_report,
        )

        forecast_report = build_regime_forecast_report(
            validation_report=markov_report,
            metastability_report=metastability_report,
            record_forecast=args.record_telemetry,
            forecast_origin="ci",
        )
        report.steps.append(
            CIStepResult(
                step="regime_forecast",
                status="PASS",
                exit_code=ManifoldExit.PASS,
                message=(
                    f"horizon={forecast_report.forecast.horizon} "
                    f"P(boundary≤N)={forecast_report.forecast.p_boundary_within:.2f} "
                    f"status={forecast_report.confidence.forecast_status} "
                    f"quality={forecast_report.forecast_quality}"
                ),
                detail=forecast_report.to_dict(),
            )
        )
        from persona_ai.diagnostics.forecast_verification import (
            build_forecast_verification_report,
            format_forecast_verification_report,
        )

        verification_report = build_forecast_verification_report()
        report.steps.append(
            CIStepResult(
                step="forecast_verification",
                status="PASS",
                exit_code=ManifoldExit.PASS,
                message=(
                    f"quality={verification_report.forecast_quality} "
                    f"verified={verification_report.verified_count}"
                ),
                detail=verification_report.to_dict(),
            )
        )
        if not args.json:
            print(
                f"  phase_snapshot={snapshot.snapshot_id} "
                f"generation={snapshot.identity.manifold_generation_id}"
            )
            print()
            print(format_markov_validation_report(markov_report))
            print()
            print(format_metastability_report(metastability_report))
            print()
            print(format_regime_forecast_report(forecast_report))
            print()
            print(format_forecast_verification_report(verification_report))

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_manifold_ci_report(report))
        if args.verbose and report.passed:
            print()
            if fixture.geometry_gate:
                print(format_geometry_gate_verdict(fixture.geometry_gate))
            print()
            print(format_arbitration_trace(fixture.arbitration))
            print()
            for decomp in fixture.decomps[:1]:
                print(format_verdict(verify_explainability_contract(decomp)))

    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
