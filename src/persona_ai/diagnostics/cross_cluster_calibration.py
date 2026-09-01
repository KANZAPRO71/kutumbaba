"""Cross-Fingerprint Calibration v1.2 — semantic cluster normalization + inter-cluster tension.

Blends local (fp_id) and shared (semantic cluster) normalization fields.
Resolves constraint interference when local optimum degrades global separation.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from persona_ai.diagnostics.fast_path_controller import ScoreDecomposition
from persona_ai.diagnostics.geometry_contract import (
    GeometrySample,
    GeometryVerdict,
    verify_geometry_contract,
)
from persona_ai.diagnostics.geometry_ci_gate import (
    GeometryGateVerdict,
    run_ci_check,
    samples_from_cross_results,
)
from persona_ai.diagnostics.surface_calibration import (
    MAX_CALIBRATION_DELTA,
    CalibratedScore,
    CalibrationFieldStore,
    CalibrationResult,
    ClusterStats,
    calibrate_s_final,
)

CALIBRATION_VERSION = "v1.2"
SCORING_SURFACE_CALIBRATION = "S_final_v1.2"

LOCAL_WEIGHT = 0.55
SHARED_WEIGHT = 0.45
MIN_INTER_CLUSTER_SEP = 0.10
TENSION_DAMPING = 0.5


def semantic_cluster_key(semantic_key: str) -> str:
    """Derive shared cluster id: FP::<failure_class> from fingerprint semantic key."""
    if not semantic_key:
        return "unknown"
    base = semantic_key.split("|")[0].strip()
    parts = base.split("::")
    if len(parts) >= 2 and parts[0] == "FP":
        return f"{parts[0]}::{parts[1]}"
    return base[:48] or "unknown"


@dataclass
class CrossClusterCalibrationResult:
    s_final_raw: float
    s_calibrated: float
    calibration_delta: float
    calibration_scale: float
    fp_id: str
    semantic_cluster: str
    local_delta: float
    shared_delta: float
    tension_factor: float
    cluster_mean: float
    cluster_std: float
    shared_mean: float
    shared_std: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CrossClusterStore(CalibrationFieldStore):
    """Extends fp-level field with semantic cluster statistics."""

    def __init__(self, path: Path | None = None):
        self.semantic_clusters: dict[str, ClusterStats] = {}
        super().__init__(path)

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        for fp_id, row in raw.get("clusters", {}).items():
            self.clusters[fp_id] = ClusterStats(
                fp_id=fp_id,
                count=row.get("count", 0),
                mean=row.get("mean", 0.5),
                m2=row.get("m2", 0.0),
            )
        for key, row in raw.get("semantic_clusters", {}).items():
            self.semantic_clusters[key] = ClusterStats(
                fp_id=key,
                count=row.get("count", 0),
                mean=row.get("mean", 0.5),
                m2=row.get("m2", 0.0),
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "calibration_version": CALIBRATION_VERSION,
            "scoring_surface": SCORING_SURFACE_CALIBRATION,
            "clusters": {
                fp_id: {"count": s.count, "mean": s.mean, "m2": s.m2, "std": s.std}
                for fp_id, s in self.clusters.items()
            },
            "semantic_clusters": {
                key: {"count": s.count, "mean": s.mean, "m2": s.m2, "std": s.std}
                for key, s in self.semantic_clusters.items()
            },
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def semantic_stats_for(self, semantic_cluster: str) -> ClusterStats:
        if semantic_cluster not in self.semantic_clusters:
            self.semantic_clusters[semantic_cluster] = ClusterStats(fp_id=semantic_cluster)
        return self.semantic_clusters[semantic_cluster]

    def observe_semantic(self, semantic_cluster: str, s_raw: float) -> ClusterStats:
        stats = self.semantic_stats_for(semantic_cluster)
        stats.update(s_raw)
        return stats


def _blend_calibration(
    s_raw: float,
    *,
    fp_id: str,
    semantic_cluster: str,
    fp_stats: ClusterStats,
    semantic_stats: ClusterStats,
) -> CrossClusterCalibrationResult:
    local = calibrate_s_final(
        s_raw, fp_id=fp_id, cluster_mean=fp_stats.mean, cluster_std=fp_stats.std
    )
    shared = calibrate_s_final(
        s_raw,
        fp_id=semantic_cluster,
        cluster_mean=semantic_stats.mean,
        cluster_std=semantic_stats.std,
    )
    blended_delta = (
        LOCAL_WEIGHT * local.calibration_delta + SHARED_WEIGHT * shared.calibration_delta
    )
    clamped = max(-MAX_CALIBRATION_DELTA, min(MAX_CALIBRATION_DELTA, blended_delta))
    s_cal = round(max(0.0, min(1.0, s_raw + clamped)), 4)

    return CrossClusterCalibrationResult(
        s_final_raw=s_raw,
        s_calibrated=s_cal,
        calibration_delta=round(clamped, 4),
        calibration_scale=round(
            (LOCAL_WEIGHT * local.calibration_scale + SHARED_WEIGHT * shared.calibration_scale),
            4,
        ),
        fp_id=fp_id,
        semantic_cluster=semantic_cluster,
        local_delta=local.calibration_delta,
        shared_delta=shared.calibration_delta,
        tension_factor=1.0,
        cluster_mean=local.cluster_mean,
        cluster_std=local.cluster_std,
        shared_mean=shared.cluster_mean,
        shared_std=shared.cluster_std,
    )


def resolve_inter_cluster_tension(
    results: list[CrossClusterCalibrationResult],
) -> list[CrossClusterCalibrationResult]:
    """Dampen calibration when semantic clusters collapse toward each other."""
    if len(results) < 2:
        return results

    cluster_values: dict[str, list[float]] = {}
    for r in results:
        cluster_values.setdefault(r.semantic_cluster, []).append(r.s_calibrated)

    centroids = {k: sum(v) / len(v) for k, v in cluster_values.items()}
    clusters = list(centroids.keys())
    if len(clusters) < 2:
        return results

    min_sep = min(
        abs(centroids[a] - centroids[b])
        for i, a in enumerate(clusters)
        for b in clusters[i + 1 :]
    )

    if min_sep >= MIN_INTER_CLUSTER_SEP:
        return results

    deficit = MIN_INTER_CLUSTER_SEP - min_sep
    tension = max(0.0, 1.0 - TENSION_DAMPING * (deficit / MIN_INTER_CLUSTER_SEP))

    adjusted: list[CrossClusterCalibrationResult] = []
    for r in results:
        damped_delta = round(r.calibration_delta * tension, 4)
        s_cal = round(max(0.0, min(1.0, r.s_final_raw + damped_delta)), 4)
        adjusted.append(
            CrossClusterCalibrationResult(
                s_final_raw=r.s_final_raw,
                s_calibrated=s_cal,
                calibration_delta=damped_delta,
                calibration_scale=r.calibration_scale,
                fp_id=r.fp_id,
                semantic_cluster=r.semantic_cluster,
                local_delta=r.local_delta,
                shared_delta=r.shared_delta,
                tension_factor=round(tension, 4),
                cluster_mean=r.cluster_mean,
                cluster_std=r.cluster_std,
                shared_mean=r.shared_mean,
                shared_std=r.shared_std,
            )
        )
    return adjusted


def calibrate_cross_cluster_batch(
    items: list[tuple[str, str, ScoreDecomposition]],
    *,
    semantic_by_fp: dict[str, str] | None = None,
    store: CrossClusterStore | None = None,
    persist: bool = False,
    run_ci_gate: bool = True,
    enforce_regression: bool = False,
) -> tuple[
    list[CalibratedScore],
    GeometryVerdict,
    list[CrossClusterCalibrationResult],
    GeometryGateVerdict | None,
]:
    """v1.2 batch calibration with semantic clusters + tension resolution."""
    field_store = store or CrossClusterStore()
    semantic_by_fp = semantic_by_fp or {}

    cross_results: list[CrossClusterCalibrationResult] = []
    decomps: list[ScoreDecomposition] = []
    patch_ids: list[str] = []

    for fp_id, patch_id, decomp in items:
        sem = semantic_cluster_key(semantic_by_fp.get(fp_id, fp_id))
        fp_stats = field_store.stats_for(fp_id)
        sem_stats = field_store.semantic_stats_for(sem)
        cross_results.append(
            _blend_calibration(
                decomp.s_final,
                fp_id=fp_id,
                semantic_cluster=sem,
                fp_stats=fp_stats,
                semantic_stats=sem_stats,
            )
        )
        decomps.append(decomp)
        patch_ids.append(patch_id)

    cross_results = resolve_inter_cluster_tension(cross_results)

    calibrated: list[CalibratedScore] = []
    for i, cr in enumerate(cross_results):
        decomp = decomps[i]
        field_store.observe(cr.fp_id, cr.s_final_raw)
        field_store.observe_semantic(cr.semantic_cluster, cr.s_final_raw)

        attempts_ok = decomp.effective_attempts >= 2.0
        eligible = (
            attempts_ok
            and cr.s_calibrated >= decomp.threshold
            and decomp.trust_state == "active"
            and decomp.contract_valid
        )
        calibrated.append(
            CalibratedScore(
                decomp=decomp,
                calibration=CalibrationResult(
                    s_final_raw=cr.s_final_raw,
                    s_calibrated=cr.s_calibrated,
                    calibration_scale=cr.calibration_scale,
                    calibration_delta=cr.calibration_delta,
                    cluster_mean=cr.cluster_mean,
                    cluster_std=cr.cluster_std,
                    fp_id=cr.fp_id,
                ),
                s_arbitration=cr.s_calibrated,
                fast_path_eligible=eligible,
            )
        )

    if persist:
        field_store.save()

    geo_samples = [
        GeometrySample(
            fp_id=cross_results[i].fp_id,
            patch_id=patch_ids[i],
            s_final_raw=cross_results[i].s_final_raw,
            s_final_calibrated=cross_results[i].s_calibrated,
        )
        for i in range(len(cross_results))
    ]
    verdict = verify_geometry_contract(geo_samples)
    gate_verdict: GeometryGateVerdict | None = None
    if run_ci_gate:
        coupled = samples_from_cross_results(cross_results, patch_ids)
        gate_verdict = run_ci_check(coupled, enforce_regression=enforce_regression)
    return calibrated, verdict, cross_results, gate_verdict


def format_cross_cluster_trace(cr: CrossClusterCalibrationResult) -> str:
    return (
        f"  S_raw={cr.s_final_raw:.3f} -> S_cal={cr.s_calibrated:.3f} "
        f"delta={cr.calibration_delta:+.3f} tension={cr.tension_factor:.2f} "
        f"local={cr.local_delta:+.3f} shared={cr.shared_delta:+.3f} "
        f"cluster={cr.semantic_cluster}"
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    from persona_ai.diagnostics.fast_path_controller import compute_S_final

    parser = argparse.ArgumentParser(description="Cross-cluster calibration v1.2")
    parser.add_argument("--sanity", action="store_true", help="CI: cross-cluster sanity check")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.sanity:
        from persona_ai.diagnostics.manifold_ci import check_cross_cluster_sanity

        result = check_cross_cluster_sanity()
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"  sanity: {result.status} — {result.message}")
        return result.exit_code

    items = [
        (
            "fp_a",
            "p1",
            compute_S_final(
                raw_score=0.72, learned_score=0.70, elasticity_weight=1.0,
                decay_factor=1.0, trust_state="active",
            ),
        ),
        (
            "fp_b",
            "p1",
            compute_S_final(
                raw_score=0.74, learned_score=0.71, elasticity_weight=1.0,
                decay_factor=1.0, trust_state="active",
            ),
        ),
        (
            "fp_c",
            "p2",
            compute_S_final(
                raw_score=0.45, learned_score=0.50, elasticity_weight=1.0,
                decay_factor=1.0, trust_state="active",
            ),
        ),
    ]
    semantic = {
        "fp_a": "FP::INTENT::CTX::ROOT",
        "fp_b": "FP::INTENT::CTX::ROOT",
        "fp_c": "FP::INCOMPLETE::DEFER::ROOT",
    }
    _, geo, cross, gate = calibrate_cross_cluster_batch(
        items, semantic_by_fp=semantic, persist=False
    )

    if args.json:
        import json as _json

        print(_json.dumps({"geometry": geo.to_dict(), "results": [r.to_dict() for r in cross]}, indent=2))
    else:
        print(f"=== Cross-Cluster Calibration | {CALIBRATION_VERSION} ===")
        for cr in cross:
            print(format_cross_cluster_trace(cr))
        print()
        from persona_ai.diagnostics.geometry_contract import format_geometry_verdict

        print(format_geometry_verdict(geo))
        if gate:
            from persona_ai.diagnostics.geometry_ci_gate import format_geometry_gate_verdict

            print()
            print(format_geometry_gate_verdict(gate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
