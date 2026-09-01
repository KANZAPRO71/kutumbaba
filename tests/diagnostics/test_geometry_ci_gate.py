"""Geometry CI Gate tests — separation invariants under coupling."""

from persona_ai.diagnostics.geometry_ci_gate import (
    CoupledGeometrySample,
    GeometryBaselineStore,
    compute_separation_metrics,
    run_ci_check,
    verify_geometry_ci_gate,
    verify_separation_invariants,
    EXIT_PASS,
    EXIT_REGRESSION,
    EXIT_VIOLATION,
    MIN_INTER_CLUSTER_DISTANCE,
    MIN_SCORE_ENTROPY,
)


def _healthy_samples() -> list[CoupledGeometrySample]:
    return [
        CoupledGeometrySample(
            fp_id="fp_a",
            patch_id="p1",
            s_final_raw=0.45,
            s_final_calibrated=0.48,
            semantic_cluster="FP::INTENT",
            local_delta=0.02,
            shared_delta=0.015,
            tension_factor=1.0,
        ),
        CoupledGeometrySample(
            fp_id="fp_b",
            patch_id="p2",
            s_final_raw=0.82,
            s_final_calibrated=0.85,
            semantic_cluster="FP::INCOMPLETE",
            local_delta=0.01,
            shared_delta=0.012,
            tension_factor=1.0,
        ),
    ]


class TestSeparationInvariants:
    def test_healthy_batch_passes_gate(self):
        verdict = verify_geometry_ci_gate(_healthy_samples(), enforce_regression=False)
        assert verdict.pass_gate
        assert verdict.exit_code() == EXIT_PASS
        assert verdict.separation.min_cluster_distance >= MIN_INTER_CLUSTER_DISTANCE
        assert verdict.separation.score_entropy >= MIN_SCORE_ENTROPY

    def test_cluster_separation_collapse_blocked(self):
        samples = [
            CoupledGeometrySample("fp_a", "p1", 0.70, 0.705, "cluster_a"),
            CoupledGeometrySample("fp_b", "p2", 0.71, 0.708, "cluster_b"),
        ]
        violations = verify_separation_invariants(samples)
        assert any(v.code == "CLUSTER_SEPARATION_COLLAPSE" for v in violations)

    def test_score_entropy_collapse_blocked(self):
        samples = [
            CoupledGeometrySample("fp_a", "p1", 0.70, 0.701, "cluster_a"),
            CoupledGeometrySample("fp_b", "p2", 0.70, 0.702, "cluster_b"),
            CoupledGeometrySample("fp_c", "p3", 0.70, 0.703, "cluster_c"),
        ]
        verdict = verify_geometry_ci_gate(samples, enforce_regression=False)
        assert not verdict.pass_gate
        assert any(v.code == "SCORE_ENTROPY_COLLAPSE" for v in verdict.violations)

    def test_coupling_asymmetry_exceeded(self):
        samples = [
            CoupledGeometrySample(
                "fp_a", "p1", 0.50, 0.55, "FP::A", local_delta=0.01, shared_delta=0.20
            ),
            CoupledGeometrySample(
                "fp_b", "p2", 0.85, 0.88, "FP::B", local_delta=0.01, shared_delta=0.18
            ),
        ]
        metrics = compute_separation_metrics(samples)
        assert metrics.coupling_asymmetry > 0.12
        verdict = verify_geometry_ci_gate(samples, enforce_regression=False)
        assert any(v.code == "COUPLING_ASYMMETRY_EXCEEDED" for v in verdict.violations)


class TestRegressionGuard:
    def test_regression_vs_baseline_detected(self, tmp_path):
        baseline_path = tmp_path / "geometry_baseline.json"
        store = GeometryBaselineStore(baseline_path)
        healthy = _healthy_samples()
        first = verify_geometry_ci_gate(healthy, enforce_regression=False)
        store.save_from_verdict(first)

        collapsed = [
            CoupledGeometrySample("fp_a", "p1", 0.70, 0.701, "FP::INTENT"),
            CoupledGeometrySample("fp_b", "p2", 0.71, 0.702, "FP::INCOMPLETE"),
        ]
        verdict = run_ci_check(collapsed, baseline_store=store, enforce_regression=True)
        assert not verdict.pass_gate
        assert verdict.regression_detected
        assert verdict.exit_code() == EXIT_REGRESSION

    def test_no_baseline_skips_regression(self):
        verdict = run_ci_check(_healthy_samples(), enforce_regression=True)
        assert verdict.pass_gate
        assert verdict.baseline_comparison is None


class TestExitCodes:
    def test_violation_exit_code(self):
        samples = [
            CoupledGeometrySample("fp_a", "p1", 0.70, 0.701),
            CoupledGeometrySample("fp_b", "p2", 0.701, 0.702),
        ]
        verdict = verify_geometry_ci_gate(samples, enforce_regression=False)
        assert verdict.exit_code() == EXIT_VIOLATION
