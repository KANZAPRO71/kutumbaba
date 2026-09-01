"""Constraint Arbitration v1.3 — equilibrium solver on the constrained manifold.

Not a multi-objective scorer. Resolves pressure between:
  - scalar correctness (S_final)
  - geometry integrity (S_calibrated)
  - cluster separation
  - coupling asymmetry
  - elasticity modulation

Feasibility-first: only CI-gate-valid states enter the solver.
No invalid generation: equilibrium is projected back onto the feasible manifold.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from persona_ai.diagnostics.cross_cluster_calibration import CrossClusterCalibrationResult
from persona_ai.diagnostics.fast_path_controller import ScoreDecomposition
from persona_ai.diagnostics.geometry_ci_gate import (
    CoupledGeometrySample,
    GeometryGateVerdict,
    SeparationMetrics,
    verify_geometry_ci_gate,
)
from persona_ai.diagnostics.surface_calibration import CalibratedScore

ARBITRATION_VERSION = "v1.3"
FEASIBILITY_DAMPING = 0.85
MAX_PROJECTION_ITER = 8
MIN_SEPARATION_NUDGE = 0.08
MAX_EQUILIBRIUM_DELTA = 0.12


@dataclass
class ConstraintWeights:
    w_scalar: float
    w_geometry: float
    w_separation: float
    w_coupling: float
    w_elasticity: float

    def normalized(self) -> ConstraintWeights:
        total = (
            self.w_scalar
            + self.w_geometry
            + self.w_separation
            + self.w_coupling
            + self.w_elasticity
        )
        if total <= 0:
            return ConstraintWeights(0.2, 0.2, 0.2, 0.2, 0.2)
        return ConstraintWeights(
            w_scalar=self.w_scalar / total,
            w_geometry=self.w_geometry / total,
            w_separation=self.w_separation / total,
            w_coupling=self.w_coupling / total,
            w_elasticity=self.w_elasticity / total,
        )

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class EnergyBreakdown:
    e_scalar: float
    e_geometry: float
    e_separation: float
    e_coupling: float
    e_elasticity: float
    e_total: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class ArbitrationCandidate:
    fp_id: str
    patch_id: str
    s_final: float
    s_calibrated: float
    elasticity_weight: float
    semantic_cluster: str
    local_delta: float
    shared_delta: float
    tension_factor: float
    trust_state: str
    contract_valid: bool
    effective_attempts: float
    threshold: float


@dataclass
class ArbitrationResult:
    candidate: ArbitrationCandidate
    s_equilibrium: float
    energy: EnergyBreakdown
    weights: ConstraintWeights
    feasible: bool
    fast_path_eligible: bool
    separation_nudge: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "fp_id": self.candidate.fp_id,
            "patch_id": self.candidate.patch_id,
            "s_final": self.candidate.s_final,
            "s_calibrated": self.candidate.s_calibrated,
            "s_equilibrium": self.s_equilibrium,
            "feasible": self.feasible,
            "fast_path_eligible": self.fast_path_eligible,
            "separation_nudge": self.separation_nudge,
            "energy": self.energy.to_dict(),
            "weights": self.weights.to_dict(),
        }


@dataclass
class BatchArbitrationVerdict:
    results: list[ArbitrationResult]
    batch_feasible: bool
    gate_admitted: bool
    weights: ConstraintWeights
    separation: SeparationMetrics | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "arbitration_version": ARBITRATION_VERSION,
            "batch_feasible": self.batch_feasible,
            "gate_admitted": self.gate_admitted,
            "weights": self.weights.to_dict(),
            "separation": self.separation.to_dict() if self.separation else None,
            "results": [result.to_dict() for result in self.results],
        }


def compute_dynamic_weights(
    *,
    separation: SeparationMetrics | None = None,
    gate_pass: bool = True,
) -> ConstraintWeights:
    """Adapt constraint weights from cluster stress — not fixed scoring blend."""
    base = ConstraintWeights(
        w_scalar=0.35,
        w_geometry=0.30,
        w_separation=0.15,
        w_coupling=0.10,
        w_elasticity=0.10,
    )
    if not gate_pass or separation is None:
        return base.normalized()

    stress = separation.coupling_stress_rate
    asym = min(separation.coupling_asymmetry / 0.12, 1.0)
    sep_deficit = max(0.0, MIN_SEPARATION_NUDGE - separation.min_cluster_distance)

    return ConstraintWeights(
        w_scalar=max(0.15, base.w_scalar - stress * 0.20 - sep_deficit * 0.5),
        w_geometry=base.w_geometry + stress * 0.25 + asym * 0.10,
        w_separation=base.w_separation + sep_deficit * 2.0 + stress * 0.15,
        w_coupling=base.w_coupling + asym * 0.20,
        w_elasticity=base.w_elasticity,
    ).normalized()


def constraint_interaction_energy(
    score: float,
    candidate: ArbitrationCandidate,
    weights: ConstraintWeights,
    *,
    separation_pressure: float = 0.0,
) -> EnergyBreakdown:
    """Formal constraint interaction energy E(s | constraints)."""
    coupling_stress = abs(candidate.shared_delta - candidate.local_delta) * (
        1.0 - candidate.tension_factor
    )
    elastic_pressure = 1.0 - candidate.elasticity_weight

    e_scalar = weights.w_scalar * (score - candidate.s_final) ** 2
    e_geometry = weights.w_geometry * (score - candidate.s_calibrated) ** 2
    e_separation = weights.w_separation * separation_pressure * (score - candidate.s_calibrated) ** 2
    e_coupling = weights.w_coupling * coupling_stress * (score - candidate.s_calibrated) ** 2
    e_elasticity = weights.w_elasticity * elastic_pressure * (score - candidate.s_final) ** 2
    e_total = e_scalar + e_geometry + e_separation + e_coupling + e_elasticity

    return EnergyBreakdown(
        e_scalar=round(e_scalar, 6),
        e_geometry=round(e_geometry, 6),
        e_separation=round(e_separation, 6),
        e_coupling=round(e_coupling, 6),
        e_elasticity=round(e_elasticity, 6),
        e_total=round(e_total, 6),
    )


def _solve_local_equilibrium(
    candidate: ArbitrationCandidate,
    weights: ConstraintWeights,
    *,
    separation_pressure: float = 0.0,
) -> float:
    """Closed-form equilibrium for quadratic constraint interaction energy."""
    coupling_stress = abs(candidate.shared_delta - candidate.local_delta) * (
        1.0 - candidate.tension_factor
    )
    elastic_pressure = 1.0 - candidate.elasticity_weight

    numerator = (
        weights.w_scalar * candidate.s_final
        + weights.w_geometry * candidate.s_calibrated
        + weights.w_coupling * coupling_stress * candidate.s_calibrated
        + weights.w_elasticity * elastic_pressure * candidate.s_final
        + weights.w_separation * separation_pressure * candidate.s_calibrated
    )
    denominator = (
        weights.w_scalar
        + weights.w_geometry
        + weights.w_coupling * coupling_stress
        + weights.w_elasticity * elastic_pressure
        + weights.w_separation * separation_pressure
    )
    if denominator <= 0:
        return candidate.s_calibrated

    raw = numerator / denominator
    delta = raw - candidate.s_calibrated
    clamped_delta = max(-MAX_EQUILIBRIUM_DELTA, min(MAX_EQUILIBRIUM_DELTA, delta))
    return round(max(0.0, min(1.0, candidate.s_calibrated + clamped_delta)), 4)


def _separation_pressure(
    candidate: ArbitrationCandidate,
    centroids: dict[str, float],
) -> float:
    """Pressure to maintain cluster separation margin."""
    if len(centroids) < 2:
        return 0.0
    own = centroids.get(candidate.semantic_cluster, candidate.s_calibrated)
    others = [value for key, value in centroids.items() if key != candidate.semantic_cluster]
    if not others:
        return 0.0
    min_dist = min(abs(own - other) for other in others)
    if min_dist >= MIN_SEPARATION_NUDGE:
        return 0.0
    return round((MIN_SEPARATION_NUDGE - min_dist) / MIN_SEPARATION_NUDGE, 4)


def _apply_separation_nudge(results: list[ArbitrationResult]) -> None:
    """Minimal batch nudge when cluster centroids collapse after equilibrium."""
    centroids: dict[str, list[float]] = {}
    for result in results:
        centroids.setdefault(result.candidate.semantic_cluster, []).append(result.s_equilibrium)
    means = {key: sum(values) / len(values) for key, values in centroids.items()}
    if len(means) < 2:
        return

    keys = list(means.keys())
    min_sep = min(abs(means[a] - means[b]) for i, a in enumerate(keys) for b in keys[i + 1 :])
    if min_sep >= MIN_SEPARATION_NUDGE:
        return

    deficit = MIN_SEPARATION_NUDGE - min_sep
    half = deficit / 2.0
    low_key = min(means, key=means.get)
    high_key = max(means, key=means.get)
    for result in results:
        if result.candidate.semantic_cluster == low_key:
            result.s_equilibrium = round(max(0.0, result.s_equilibrium - half), 4)
            result.separation_nudge = round(-half, 4)
        elif result.candidate.semantic_cluster == high_key:
            result.s_equilibrium = round(min(1.0, result.s_equilibrium + half), 4)
            result.separation_nudge = round(half, 4)


def _to_coupled_samples(results: list[ArbitrationResult]) -> list[CoupledGeometrySample]:
    return [
        CoupledGeometrySample(
            fp_id=result.candidate.fp_id,
            patch_id=result.candidate.patch_id,
            s_final_raw=result.candidate.s_final,
            s_final_calibrated=result.s_equilibrium,
            semantic_cluster=result.candidate.semantic_cluster,
            local_delta=result.candidate.local_delta,
            shared_delta=result.candidate.shared_delta,
            tension_factor=result.candidate.tension_factor,
        )
        for result in results
    ]


def project_to_feasible_manifold(results: list[ArbitrationResult]) -> bool:
    """Project equilibrium scores back onto CI-gate-feasible manifold."""
    for _ in range(MAX_PROJECTION_ITER):
        verdict = verify_geometry_ci_gate(_to_coupled_samples(results), enforce_regression=False)
        if verdict.pass_gate:
            for result in results:
                result.feasible = True
                result.energy = constraint_interaction_energy(
                    result.s_equilibrium,
                    result.candidate,
                    result.weights,
                )
            return True
        for result in results:
            projected = result.candidate.s_calibrated + FEASIBILITY_DAMPING * (
                result.s_equilibrium - result.candidate.s_calibrated
            )
            result.s_equilibrium = round(max(0.0, min(1.0, projected)), 4)

    for result in results:
        result.feasible = False
    return False


def _fast_path_eligible(result: ArbitrationResult) -> bool:
    candidate = result.candidate
    return (
        result.feasible
        and candidate.contract_valid
        and candidate.trust_state == "active"
        and candidate.effective_attempts >= 2.0
        and result.s_equilibrium >= candidate.threshold
    )


def build_candidate(
    calibrated: CalibratedScore,
    cross: CrossClusterCalibrationResult,
    patch_id: str,
) -> ArbitrationCandidate:
    decomp = calibrated.decomp
    return ArbitrationCandidate(
        fp_id=cross.fp_id,
        patch_id=patch_id,
        s_final=decomp.s_final,
        s_calibrated=cross.s_calibrated,
        elasticity_weight=decomp.elasticity_weight,
        semantic_cluster=cross.semantic_cluster,
        local_delta=cross.local_delta,
        shared_delta=cross.shared_delta,
        tension_factor=cross.tension_factor,
        trust_state=decomp.trust_state,
        contract_valid=decomp.contract_valid,
        effective_attempts=decomp.effective_attempts,
        threshold=decomp.threshold,
    )


def arbitrate_feasible_batch(
    candidates: list[ArbitrationCandidate],
    *,
    gate_verdict: GeometryGateVerdict | None = None,
) -> BatchArbitrationVerdict:
    """Equilibrium solver — feasibility-first, no invalid generation."""
    gate_admitted = gate_verdict.pass_gate if gate_verdict else True
    separation = gate_verdict.separation if gate_verdict else None
    weights = compute_dynamic_weights(separation=separation, gate_pass=gate_admitted)

    if not gate_admitted or not candidates:
        return BatchArbitrationVerdict(
            results=[],
            batch_feasible=False,
            gate_admitted=gate_admitted,
            weights=weights,
            separation=separation,
        )

    provisional_centroids: dict[str, float] = {}
    for candidate in candidates:
        provisional_centroids.setdefault(candidate.semantic_cluster, candidate.s_calibrated)

    results: list[ArbitrationResult] = []
    for candidate in candidates:
        sep_pressure = _separation_pressure(candidate, provisional_centroids)
        s_eq = _solve_local_equilibrium(candidate, weights, separation_pressure=sep_pressure)
        energy = constraint_interaction_energy(
            s_eq, candidate, weights, separation_pressure=sep_pressure
        )
        results.append(
            ArbitrationResult(
                candidate=candidate,
                s_equilibrium=s_eq,
                energy=energy,
                weights=weights,
                feasible=False,
                fast_path_eligible=False,
            )
        )

    _apply_separation_nudge(results)
    for result in results:
        result.energy = constraint_interaction_energy(
            result.s_equilibrium, result.candidate, weights
        )

    batch_feasible = project_to_feasible_manifold(results)
    for result in results:
        result.fast_path_eligible = _fast_path_eligible(result)

    return BatchArbitrationVerdict(
        results=results,
        batch_feasible=batch_feasible,
        gate_admitted=gate_admitted,
        weights=weights,
        separation=separation,
    )


def arbitrate_from_calibration(
    calibrated_list: list[CalibratedScore],
    cross_results: list[CrossClusterCalibrationResult],
    patch_ids: list[str],
    *,
    gate_verdict: GeometryGateVerdict | None = None,
) -> BatchArbitrationVerdict:
    candidates = [
        build_candidate(calibrated_list[i], cross_results[i], patch_ids[i])
        for i in range(len(calibrated_list))
    ]
    return arbitrate_feasible_batch(candidates, gate_verdict=gate_verdict)


def format_arbitration_trace(verdict: BatchArbitrationVerdict) -> str:
    status = "FEASIBLE" if verdict.batch_feasible else "INFEASIBLE"
    lines = [
        f"=== Constraint Arbitration | {ARBITRATION_VERSION} ===",
        f"  status: {status} | gate_admitted={verdict.gate_admitted}",
        (
            f"  weights: scalar={verdict.weights.w_scalar:.2f} "
            f"geometry={verdict.weights.w_geometry:.2f} "
            f"separation={verdict.weights.w_separation:.2f} "
            f"coupling={verdict.weights.w_coupling:.2f} "
            f"elasticity={verdict.weights.w_elasticity:.2f}"
        ),
    ]
    for result in verdict.results:
        candidate = result.candidate
        lines.append(
            f"  [{candidate.patch_id}] S_raw={candidate.s_final:.3f} "
            f"S_cal={candidate.s_calibrated:.3f} -> S_eq={result.s_equilibrium:.3f} "
            f"E={result.energy.e_total:.5f} feasible={result.feasible} "
            f"fp={result.fast_path_eligible}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    from persona_ai.diagnostics.cross_cluster_calibration import calibrate_cross_cluster_batch
    from persona_ai.diagnostics.fast_path_controller import compute_S_final

    parser = argparse.ArgumentParser(description="Constraint arbitration v1.3 equilibrium solver")
    parser.add_argument("--check-feasibility", action="store_true", help="CI: fail if equilibrium INFEASIBLE")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.check_feasibility:
        from persona_ai.diagnostics.manifold_ci import check_constraint_arbitration, build_canonical_fixture

        result = check_constraint_arbitration(build_canonical_fixture())
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(format_arbitration_trace(build_canonical_fixture().arbitration))
            print(f"  feasibility: {result.status} — {result.message}")
        return result.exit_code

    items = [
        (
            "fp_a",
            "p1",
            compute_S_final(
                raw_score=0.72,
                learned_score=0.70,
                elasticity_weight=0.9,
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
    semantic = {
        "fp_a": "FP::INTENT::CTX::ROOT",
        "fp_b": "FP::INCOMPLETE::DEFER::ROOT",
    }
    calibrated, _, cross, gate = calibrate_cross_cluster_batch(
        items, semantic_by_fp=semantic, persist=False
    )
    verdict = arbitrate_from_calibration(
        calibrated, cross, ["p1", "p2"], gate_verdict=gate
    )

    if args.json:
        print(json.dumps(verdict.to_dict(), indent=2))
    else:
        print(format_arbitration_trace(verdict))
    return 0 if verdict.batch_feasible else 1


if __name__ == "__main__":
    raise SystemExit(main())
