"""Geometry contract and surface calibration v1.1 tests."""

from persona_ai.diagnostics.fast_path_controller import compute_S_final
from persona_ai.diagnostics.geometry_contract import (
    GeometrySample,
    verify_geometry_contract,
)
from persona_ai.diagnostics.surface_calibration import (
    CalibrationFieldStore,
    calibrate_batch,
    calibrate_s_final,
)


class TestGeometryContract:
    def test_healthy_spread(self):
        samples = [
            GeometrySample("fp_a", "p1", 0.45, 0.48),
            GeometrySample("fp_b", "p2", 0.72, 0.75),
            GeometrySample("fp_c", "p3", 0.88, 0.90),
        ]
        verdict = verify_geometry_contract(samples)
        assert verdict.valid
        assert verdict.spread_std >= 0.04

    def test_collapse_detected(self):
        samples = [
            GeometrySample("fp_a", "p1", 0.70),
            GeometrySample("fp_b", "p2", 0.71),
            GeometrySample("fp_c", "p3", 0.705),
        ]
        verdict = verify_geometry_contract(samples)
        assert not verdict.valid
        assert any(v.code == "DISTRIBUTION_COLLAPSE" for v in verdict.violations)


class TestSurfaceCalibration:
    def test_monotonic_preserves_rank(self):
        store = CalibrationFieldStore()
        stats = store.stats_for("fp_x")
        stats.mean = 0.7
        stats.count = 10
        stats.m2 = 0.01

        low = calibrate_s_final(0.65, fp_id="fp_x", cluster_mean=stats.mean, cluster_std=stats.std)
        high = calibrate_s_final(0.75, fp_id="fp_x", cluster_mean=stats.mean, cluster_std=stats.std)
        assert low.s_calibrated <= high.s_calibrated

    def test_max_delta_bounded(self):
        cal = calibrate_s_final(0.82, fp_id="fp_y", cluster_mean=0.5, cluster_std=0.05)
        assert abs(cal.calibration_delta) <= 0.15

    def test_batch_calibration(self):
        items = [
            (
                "fp_a",
                "p1",
                compute_S_final(
                    raw_score=0.85,
                    learned_score=0.80,
                    elasticity_weight=1.0,
                    decay_factor=1.0,
                    trust_state="active",
                ),
            ),
            (
                "fp_b",
                "p2",
                compute_S_final(
                    raw_score=0.55,
                    learned_score=0.50,
                    elasticity_weight=1.0,
                    decay_factor=1.0,
                    trust_state="active",
                ),
            ),
        ]
        results, geo = calibrate_batch(items)
        assert len(results) == 2
        assert all(r.decomp.contract_valid for r in results)
        assert geo.rank_preservation == 1.0
