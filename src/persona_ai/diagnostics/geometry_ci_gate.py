"""Geometry CI Gate v1 — hard boundary for distribution integrity under coupling.

Extends the scalar geometry contract with separation invariants required once
cross-cluster calibration couples local and global fields:

  1. Min inter-cluster distance (centroid separation)
  2. Score entropy bound (distribution informativeness)
  3. Distance entropy bound (cluster spacing diversity)
  4. Coupling asymmetry limit (local vs shared field divergence)
  5. Regression guard vs frozen baseline snapshot

Exit codes: 0 = pass, 1 = invariant violation, 2 = regression vs baseline.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from persona_ai.diagnostics.geometry_contract import (
    GEOMETRY_CONTRACT_VERSION,
    GeometrySample,
    GeometryVerdict,
    format_geometry_verdict,
    verify_geometry_contract,
)

GATE_VERSION = "v1"

MIN_INTER_CLUSTER_DISTANCE = 0.08
MIN_SCORE_ENTROPY = 0.40
MIN_DISTANCE_ENTROPY = 0.30
MAX_COUPLING_ASYMMETRY = 0.12
REGRESSION_TOLERANCE = 0.02

DEFAULT_BASELINE_PATH = Path(".persona_ai/geometry_baseline.json")

EXIT_PASS = 0
EXIT_VIOLATION = 1
EXIT_REGRESSION = 2


@dataclass
class CoupledGeometrySample:
    fp_id: str
    patch_id: str
    s_final_raw: float
    s_final_calibrated: float | None = None
    semantic_cluster: str = ""
    local_delta: float = 0.0
    shared_delta: float = 0.0
    tension_factor: float = 1.0

    @property
    def s_effective(self) -> float:
        return self.s_final_calibrated if self.s_final_calibrated is not None else self.s_final_raw

    def to_geometry_sample(self) -> GeometrySample:
        return GeometrySample(
            fp_id=self.fp_id,
            patch_id=self.patch_id,
            s_final_raw=self.s_final_raw,
            s_final_calibrated=self.s_final_calibrated,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SeparationMetrics:
    min_cluster_distance: float
    score_entropy: float
    distance_entropy: float
    coupling_asymmetry: float
    coupling_stress_rate: float
    cluster_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateViolation:
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GeometryGateVerdict:
    pass_gate: bool
    base_geometry: GeometryVerdict
    separation: SeparationMetrics
    violations: list[GateViolation]
    regression_detected: bool = False
    baseline_comparison: dict[str, Any] | None = None

    @property
    def valid(self) -> bool:
        return self.pass_gate

    def exit_code(self) -> int:
        if self.pass_gate:
            return EXIT_PASS
        if self.regression_detected:
            return EXIT_REGRESSION
        return EXIT_VIOLATION

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass_gate": self.pass_gate,
            "gate_version": GATE_VERSION,
            "geometry_contract_version": GEOMETRY_CONTRACT_VERSION,
            "base_geometry": self.base_geometry.to_dict(),
            "separation": self.separation.to_dict(),
            "violations": [v.to_dict() for v in self.violations],
            "regression_detected": self.regression_detected,
            "baseline_comparison": self.baseline_comparison,
            "exit_code": self.exit_code(),
        }


def normalized_binned_entropy(values: list[float], *, bins: int = 10) -> float:
    if not values:
        return 0.0
    effective_bins = min(bins, max(2, len(values)))
    counts = [0] * effective_bins
    for value in values:
        idx = min(effective_bins - 1, max(0, int(value * effective_bins)))
        counts[idx] += 1
    total = len(values)
    entropy = 0.0
    for count in counts:
        if count > 0:
            probability = count / total
            entropy -= probability * math.log2(probability)
    max_entropy = math.log2(effective_bins)
    return round(entropy / max_entropy, 4) if max_entropy > 0 else 0.0


def _cluster_centroids(samples: list[CoupledGeometrySample]) -> dict[str, float]:
    groups: dict[str, list[float]] = {}
    for sample in samples:
        key = sample.semantic_cluster or sample.fp_id
        groups.setdefault(key, []).append(sample.s_effective)
    return {key: sum(values) / len(values) for key, values in groups.items()}


def _min_inter_cluster_distance(centroids: dict[str, float]) -> float:
    keys = list(centroids.keys())
    if len(keys) < 2:
        return 1.0
    return round(
        min(abs(centroids[a] - centroids[b]) for i, a in enumerate(keys) for b in keys[i + 1 :]),
        4,
    )


def _pairwise_distances(centroids: dict[str, float]) -> list[float]:
    keys = list(centroids.keys())
    return [abs(centroids[a] - centroids[b]) for i, a in enumerate(keys) for b in keys[i + 1 :]]


def _distance_entropy(centroids: dict[str, float]) -> float:
    distances = _pairwise_distances(centroids)
    if not distances:
        return 1.0
    if len(distances) < 2:
        return round(min(1.0, distances[0] / 0.5), 4)
    return normalized_binned_entropy(distances, bins=min(5, len(distances)))


def compute_separation_metrics(samples: list[CoupledGeometrySample]) -> SeparationMetrics:
    centroids = _cluster_centroids(samples)
    effective = [sample.s_effective for sample in samples]
    coupling_deltas = [
        abs(sample.shared_delta - sample.local_delta)
        for sample in samples
        if sample.shared_delta or sample.local_delta
    ]
    stressed = sum(1 for sample in samples if sample.tension_factor < 1.0)
    return SeparationMetrics(
        min_cluster_distance=_min_inter_cluster_distance(centroids),
        score_entropy=normalized_binned_entropy(effective),
        distance_entropy=_distance_entropy(centroids),
        coupling_asymmetry=round(sum(coupling_deltas) / len(coupling_deltas), 4)
        if coupling_deltas
        else 0.0,
        coupling_stress_rate=round(stressed / len(samples), 3) if samples else 0.0,
        cluster_count=len(centroids),
    )


def verify_separation_invariants(
    samples: list[CoupledGeometrySample],
    metrics: SeparationMetrics | None = None,
) -> list[GateViolation]:
    metrics = metrics or compute_separation_metrics(samples)
    violations: list[GateViolation] = []

    if metrics.cluster_count >= 2 and metrics.min_cluster_distance < MIN_INTER_CLUSTER_DISTANCE:
        violations.append(
            GateViolation(
                code="CLUSTER_SEPARATION_COLLAPSE",
                message=(
                    f"min inter-cluster distance {metrics.min_cluster_distance:.4f} "
                    f"< {MIN_INTER_CLUSTER_DISTANCE}"
                ),
                detail={
                    "min_cluster_distance": metrics.min_cluster_distance,
                    "min_required": MIN_INTER_CLUSTER_DISTANCE,
                    "cluster_count": metrics.cluster_count,
                },
            )
        )
    if len(samples) >= 3 and metrics.score_entropy < MIN_SCORE_ENTROPY:
        violations.append(
            GateViolation(
                code="SCORE_ENTROPY_COLLAPSE",
                message=(
                    f"score entropy {metrics.score_entropy:.4f} below minimum {MIN_SCORE_ENTROPY}"
                ),
                detail={"score_entropy": metrics.score_entropy, "min_required": MIN_SCORE_ENTROPY},
            )
        )
    if metrics.cluster_count >= 2 and metrics.distance_entropy < MIN_DISTANCE_ENTROPY:
        violations.append(
            GateViolation(
                code="DISTANCE_ENTROPY_COLLAPSE",
                message=(
                    f"distance entropy {metrics.distance_entropy:.4f} "
                    f"below minimum {MIN_DISTANCE_ENTROPY}"
                ),
                detail={
                    "distance_entropy": metrics.distance_entropy,
                    "min_required": MIN_DISTANCE_ENTROPY,
                },
            )
        )
    if metrics.coupling_asymmetry > MAX_COUPLING_ASYMMETRY:
        violations.append(
            GateViolation(
                code="COUPLING_ASYMMETRY_EXCEEDED",
                message=(
                    f"coupling asymmetry {metrics.coupling_asymmetry:.4f} "
                    f"> max {MAX_COUPLING_ASYMMETRY}"
                ),
                detail={
                    "coupling_asymmetry": metrics.coupling_asymmetry,
                    "max_allowed": MAX_COUPLING_ASYMMETRY,
                },
            )
        )
    return violations


def _compare_baseline(
    metrics: SeparationMetrics,
    base_geometry: GeometryVerdict,
    baseline: dict[str, Any],
) -> tuple[list[GateViolation], dict[str, Any]]:
    violations: list[GateViolation] = []
    comparison: dict[str, Any] = {"baseline_version": baseline.get("gate_version", "?")}

    checks = [
        ("spread_std", base_geometry.spread_std, baseline.get("spread_std", 0.0)),
        ("min_cluster_distance", metrics.min_cluster_distance, baseline.get("min_cluster_distance", 0.0)),
        ("score_entropy", metrics.score_entropy, baseline.get("score_entropy", 0.0)),
        ("distance_entropy", metrics.distance_entropy, baseline.get("distance_entropy", 0.0)),
    ]
    for name, current, previous in checks:
        delta = round(previous - current, 4)
        comparison[name] = {"current": current, "baseline": previous, "delta": delta}
        if previous > 0 and delta > REGRESSION_TOLERANCE:
            violations.append(
                GateViolation(
                    code="GEOMETRY_REGRESSION",
                    message=f"{name} regressed by {delta:.4f} (tolerance {REGRESSION_TOLERANCE})",
                    detail={"metric": name, "current": current, "baseline": previous, "delta": delta},
                )
            )
    return violations, comparison


class GeometryBaselineStore:
    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_BASELINE_PATH

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save_from_verdict(self, verdict: GeometryGateVerdict) -> None:
        payload = {
            "gate_version": GATE_VERSION,
            "geometry_contract_version": GEOMETRY_CONTRACT_VERSION,
            "spread_std": verdict.base_geometry.spread_std,
            "min_cluster_distance": verdict.separation.min_cluster_distance,
            "score_entropy": verdict.separation.score_entropy,
            "distance_entropy": verdict.separation.distance_entropy,
            "coupling_asymmetry": verdict.separation.coupling_asymmetry,
            "cluster_count": verdict.separation.cluster_count,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def verify_geometry_ci_gate(
    samples: list[CoupledGeometrySample],
    *,
    baseline: dict[str, Any] | None = None,
    enforce_regression: bool = True,
) -> GeometryGateVerdict:
    """Full coupled geometry gate: base contract + separation + optional regression."""
    base_geometry = verify_geometry_contract([sample.to_geometry_sample() for sample in samples])
    separation = compute_separation_metrics(samples)

    violations: list[GateViolation] = []
    if not base_geometry.valid:
        for violation in base_geometry.violations:
            violations.append(
                GateViolation(
                    code=violation.code,
                    message=violation.message,
                    detail=violation.detail,
                )
            )
    violations.extend(verify_separation_invariants(samples, separation))

    regression_detected = False
    baseline_comparison: dict[str, Any] | None = None
    if enforce_regression and baseline:
        regression_violations, baseline_comparison = _compare_baseline(
            separation, base_geometry, baseline
        )
        if regression_violations:
            regression_detected = True
            violations.extend(regression_violations)

    pass_gate = len(violations) == 0
    return GeometryGateVerdict(
        pass_gate=pass_gate,
        base_geometry=base_geometry,
        separation=separation,
        violations=violations,
        regression_detected=regression_detected,
        baseline_comparison=baseline_comparison,
    )


def samples_from_cross_results(
    cross_results: list[Any],
    patch_ids: list[str],
) -> list[CoupledGeometrySample]:
    return [
        CoupledGeometrySample(
            fp_id=result.fp_id,
            patch_id=patch_ids[i],
            s_final_raw=result.s_final_raw,
            s_final_calibrated=result.s_calibrated,
            semantic_cluster=result.semantic_cluster,
            local_delta=result.local_delta,
            shared_delta=result.shared_delta,
            tension_factor=result.tension_factor,
        )
        for i, result in enumerate(cross_results)
    ]


def format_geometry_gate_verdict(verdict: GeometryGateVerdict) -> str:
    status = "PASS" if verdict.pass_gate else "BLOCKED"
    lines = [
        f"=== Geometry CI Gate | {GATE_VERSION} ===",
        f"  status: {status} | exit={verdict.exit_code()}",
        format_geometry_verdict(verdict.base_geometry),
        (
            f"  separation: min_dist={verdict.separation.min_cluster_distance:.4f} "
            f"score_H={verdict.separation.score_entropy:.4f} "
            f"dist_H={verdict.separation.distance_entropy:.4f} "
            f"coupling={verdict.separation.coupling_asymmetry:.4f} "
            f"stress={verdict.separation.coupling_stress_rate:.0%} "
            f"clusters={verdict.separation.cluster_count}"
        ),
    ]
    for violation in verdict.violations:
        lines.append(f"  [GATE:{violation.code}] {violation.message}")
    if verdict.baseline_comparison:
        lines.append(f"  baseline_comparison: {verdict.baseline_comparison}")
    return "\n".join(lines)


def run_ci_check(
    samples: list[CoupledGeometrySample],
    *,
    baseline_store: GeometryBaselineStore | None = None,
    enforce_regression: bool = True,
) -> GeometryGateVerdict:
    store = baseline_store or GeometryBaselineStore()
    baseline = store.load() if enforce_regression else None
    return verify_geometry_ci_gate(
        samples, baseline=baseline, enforce_regression=enforce_regression
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    from persona_ai.diagnostics.cross_cluster_calibration import calibrate_cross_cluster_batch
    from persona_ai.diagnostics.fast_path_controller import compute_S_final

    parser = argparse.ArgumentParser(description="Geometry CI Gate — distribution firewall")
    parser.add_argument("--check", action="store_true", help="Run gate check (default action)")
    parser.add_argument("--ci", action="store_true", help="CI alias for --check --demo")
    parser.add_argument("--update-baseline", action="store_true", help="Save baseline after pass")
    parser.add_argument("--no-regression", action="store_true", help="Skip baseline regression")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--samples-file", type=Path, help="JSON list of CoupledGeometrySample dicts")
    parser.add_argument("--demo", action="store_true", help="Run built-in demo batch")
    args = parser.parse_args(argv)

    if args.ci:
        args.check = True
        args.demo = True
        args.no_regression = True

    samples: list[CoupledGeometrySample] = []
    if args.samples_file:
        raw = json.loads(args.samples_file.read_text(encoding="utf-8"))
        samples = [CoupledGeometrySample(**row) for row in raw]
    elif args.demo or not args.samples_file:
        demo_items = [
            (
                "fp_a",
                "p1",
                compute_S_final(
                    raw_score=0.72,
                    learned_score=0.70,
                    elasticity_weight=1.0,
                    decay_factor=1.0,
                    trust_state="active",
                ),
            ),
            (
                "fp_b",
                "p2",
                compute_S_final(
                    raw_score=0.45,
                    learned_score=0.50,
                    elasticity_weight=1.0,
                    decay_factor=1.0,
                    trust_state="active",
                ),
            ),
        ]
        semantic = {"fp_a": "FP::INTENT::CTX::ROOT", "fp_b": "FP::INCOMPLETE::DEFER::ROOT"}
        _, _, cross, _ = calibrate_cross_cluster_batch(demo_items, semantic_by_fp=semantic)
        samples = samples_from_cross_results(cross, ["p1", "p2"])

    store = GeometryBaselineStore()
    verdict = run_ci_check(
        samples,
        baseline_store=store,
        enforce_regression=not args.no_regression,
    )

    if args.update_baseline:
        if verdict.pass_gate:
            store.save_from_verdict(verdict)
        else:
            print("Baseline NOT updated — gate failed", file=__import__("sys").stderr)
            if args.json:
                print(json.dumps(verdict.to_dict(), indent=2))
            else:
                print(format_geometry_gate_verdict(verdict))
            return verdict.exit_code()

    if args.json:
        print(json.dumps(verdict.to_dict(), indent=2))
    else:
        print(format_geometry_gate_verdict(verdict))
    return verdict.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
