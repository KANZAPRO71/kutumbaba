"""Cross-fingerprint calibration v1.2 tests."""

from persona_ai.diagnostics.cross_cluster_calibration import (
    CrossClusterStore,
    calibrate_cross_cluster_batch,
    resolve_inter_cluster_tension,
    semantic_cluster_key,
)
from persona_ai.diagnostics.cross_cluster_calibration import CrossClusterCalibrationResult
from persona_ai.diagnostics.fast_path_controller import compute_S_final


def _decomp(raw: float) -> object:
    return compute_S_final(
        raw_score=raw,
        learned_score=raw - 0.05,
        elasticity_weight=1.0,
        decay_factor=1.0,
        trust_state="active",
    )


class TestSemanticClusterKey:
    def test_strips_subtype(self):
        assert semantic_cluster_key("FP::INTENT|instructional_intent") == "FP::INTENT"

    def test_unknown_fallback(self):
        assert semantic_cluster_key("") == "unknown"


class TestCrossClusterCalibration:
    def test_semantic_cluster_stats_shared(self):
        store = CrossClusterStore()
        store.semantic_stats_for("FP::INTENT").mean = 0.7
        store.semantic_stats_for("FP::INTENT").count = 5
        store.semantic_stats_for("FP::INTENT").m2 = 0.05

        items = [
            ("fp_a", "p1", _decomp(0.72)),
            ("fp_b", "p1", _decomp(0.74)),
        ]
        semantic = {
            "fp_a": "FP::INTENT|instructional_intent",
            "fp_b": "FP::INTENT|instructional_intent",
        }
        _, geo, cross, _ = calibrate_cross_cluster_batch(
            items, semantic_by_fp=semantic, store=store, persist=False
        )
        assert len(cross) == 2
        assert cross[0].semantic_cluster == cross[1].semantic_cluster == "FP::INTENT"
        assert geo.rank_preservation == 1.0

    def test_tension_dampens_collapsing_clusters(self):
        results = [
            CrossClusterCalibrationResult(
                s_final_raw=0.70,
                s_calibrated=0.73,
                calibration_delta=0.03,
                calibration_scale=1.0,
                fp_id="fp_a",
                semantic_cluster="cluster_a",
                local_delta=0.03,
                shared_delta=0.02,
                tension_factor=1.0,
                cluster_mean=0.7,
                cluster_std=0.08,
                shared_mean=0.7,
                shared_std=0.08,
            ),
            CrossClusterCalibrationResult(
                s_final_raw=0.71,
                s_calibrated=0.735,
                calibration_delta=0.025,
                calibration_scale=1.0,
                fp_id="fp_b",
                semantic_cluster="cluster_b",
                local_delta=0.025,
                shared_delta=0.02,
                tension_factor=1.0,
                cluster_mean=0.7,
                cluster_std=0.08,
                shared_mean=0.71,
                shared_std=0.08,
            ),
        ]
        adjusted = resolve_inter_cluster_tension(results)
        assert all(r.tension_factor < 1.0 for r in adjusted)
        assert adjusted[0].calibration_delta < results[0].calibration_delta
        assert adjusted[1].calibration_delta < results[1].calibration_delta

    def test_separate_semantic_clusters_preserved(self):
        items = [
            ("fp_a", "p1", _decomp(0.82)),
            ("fp_b", "p2", _decomp(0.45)),
        ]
        semantic = {
            "fp_a": "FP::INTENT::CTX::ROOT",
            "fp_b": "FP::INCOMPLETE::DEFER::ROOT",
        }
        _, geo, cross, gate = calibrate_cross_cluster_batch(
            items, semantic_by_fp=semantic, persist=False
        )
        assert cross[0].semantic_cluster != cross[1].semantic_cluster
        assert geo.valid
        assert gate is not None
        assert gate.pass_gate

    def test_max_delta_bounded(self):
        items = [("fp_x", "p1", _decomp(0.90))]
        _, _, cross, _ = calibrate_cross_cluster_batch(items, persist=False)
        assert abs(cross[0].calibration_delta) <= 0.15
