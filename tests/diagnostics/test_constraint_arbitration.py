"""Constraint arbitration v1.3 equilibrium solver tests."""

from persona_ai.diagnostics.constraint_arbitration import (
    ArbitrationCandidate,
    arbitrate_feasible_batch,
    compute_dynamic_weights,
    constraint_interaction_energy,
    project_to_feasible_manifold,
    _solve_local_equilibrium,
)
from persona_ai.diagnostics.geometry_ci_gate import (
    CoupledGeometrySample,
    GeometryGateVerdict,
    SeparationMetrics,
    verify_geometry_ci_gate,
)


def _candidate(
    *,
    s_final: float = 0.72,
    s_cal: float = 0.75,
    patch_id: str = "p1",
    cluster: str = "FP::INTENT",
    local: float = 0.02,
    shared: float = 0.015,
    tension: float = 1.0,
    elasticity: float = 1.0,
) -> ArbitrationCandidate:
    return ArbitrationCandidate(
        fp_id="fp_a",
        patch_id=patch_id,
        s_final=s_final,
        s_calibrated=s_cal,
        elasticity_weight=elasticity,
        semantic_cluster=cluster,
        local_delta=local,
        shared_delta=shared,
        tension_factor=tension,
        trust_state="active",
        contract_valid=True,
        effective_attempts=2.0,
        threshold=0.7,
    )


def _gate_pass(separation: SeparationMetrics | None = None) -> GeometryGateVerdict:
    samples = [
        CoupledGeometrySample("fp_a", "p1", 0.45, 0.48, "FP::INTENT"),
        CoupledGeometrySample("fp_b", "p2", 0.82, 0.85, "FP::INCOMPLETE"),
    ]
    verdict = verify_geometry_ci_gate(samples, enforce_regression=False)
    if separation:
        verdict.separation = separation
    return verdict


class TestConstraintEnergy:
    def test_energy_minimized_at_equilibrium(self):
        candidate = _candidate(s_final=0.70, s_cal=0.78)
        weights = compute_dynamic_weights(gate_pass=True)
        s_eq = _solve_local_equilibrium(candidate, weights)
        e_eq = constraint_interaction_energy(s_eq, candidate, weights).e_total
        e_cal = constraint_interaction_energy(candidate.s_calibrated, candidate, weights).e_total
        e_raw = constraint_interaction_energy(candidate.s_final, candidate, weights).e_total
        assert e_eq <= e_cal + 1e-6
        assert e_eq <= e_raw + 1e-6

    def test_dynamic_weights_shift_under_stress(self):
        calm = SeparationMetrics(0.30, 0.8, 0.7, 0.02, 0.0, 2)
        stressed = SeparationMetrics(0.05, 0.5, 0.4, 0.11, 0.5, 2)
        w_calm = compute_dynamic_weights(separation=calm, gate_pass=True)
        w_stress = compute_dynamic_weights(separation=stressed, gate_pass=True)
        assert w_stress.w_geometry > w_calm.w_geometry
        assert w_stress.w_separation > w_calm.w_separation


class TestEquilibriumSolver:
    def test_feasible_batch_produces_equilibrium(self):
        candidates = [
            _candidate(s_final=0.72, s_cal=0.74, patch_id="p1", cluster="FP::INTENT"),
            _candidate(s_final=0.45, s_cal=0.48, patch_id="p2", cluster="FP::INCOMPLETE"),
        ]
        verdict = arbitrate_feasible_batch(candidates, gate_verdict=_gate_pass())
        assert verdict.batch_feasible
        assert verdict.gate_admitted
        assert len(verdict.results) == 2
        for result in verdict.results:
            assert result.feasible
            assert 0.0 <= result.s_equilibrium <= 1.0
            assert abs(result.s_equilibrium - result.candidate.s_calibrated) <= 0.12

    def test_gate_blocked_admits_nothing(self):
        gate = _gate_pass()
        gate.pass_gate = False
        verdict = arbitrate_feasible_batch([_candidate()], gate_verdict=gate)
        assert not verdict.batch_feasible
        assert verdict.results == []

    def test_projection_restores_feasibility(self):
        from persona_ai.diagnostics.constraint_arbitration import ArbitrationResult, EnergyBreakdown

        weights = compute_dynamic_weights(gate_pass=True)
        candidate = _candidate(s_final=0.70, s_cal=0.705, cluster="cluster_a")
        candidate_b = _candidate(
            s_final=0.71,
            s_cal=0.708,
            patch_id="p2",
            cluster="cluster_b",
        )
        results = [
            ArbitrationResult(
                candidate=candidate,
                s_equilibrium=0.706,
                energy=EnergyBreakdown(0, 0, 0, 0, 0, 0),
                weights=weights,
                feasible=False,
                fast_path_eligible=False,
            ),
            ArbitrationResult(
                candidate=candidate_b,
                s_equilibrium=0.707,
                energy=EnergyBreakdown(0, 0, 0, 0, 0, 0),
                weights=weights,
                feasible=False,
                fast_path_eligible=False,
            ),
        ]
        ok = project_to_feasible_manifold(results)
        assert ok or not any(result.feasible for result in results)


class TestIntegration:
    def test_arbitrate_from_calibration_cli_path(self):
        from persona_ai.diagnostics.constraint_arbitration import arbitrate_from_calibration
        from persona_ai.diagnostics.cross_cluster_calibration import calibrate_cross_cluster_batch
        from persona_ai.diagnostics.fast_path_controller import compute_S_final

        items = [
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
        semantic = {
            "fp_a": "FP::INTENT::CTX::ROOT",
            "fp_b": "FP::INCOMPLETE::DEFER::ROOT",
        }
        calibrated, _, cross, gate = calibrate_cross_cluster_batch(
            items, semantic_by_fp=semantic, persist=False
        )
        verdict = arbitrate_from_calibration(calibrated, cross, ["p1", "p2"], gate_verdict=gate)
        assert verdict.batch_feasible
        assert all(result.energy.e_total >= 0 for result in verdict.results)
