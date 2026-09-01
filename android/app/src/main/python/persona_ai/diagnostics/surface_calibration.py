"""Surface Calibration v1.1 — sensitivity-preserving distribution shaping.

Applies AFTER scalar S_final + contract verify. Does NOT mutate decomposition
invariants — calibrated score is a separate field for runtime arbitration.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from persona_ai.diagnostics.fast_path_controller import ScoreDecomposition
from persona_ai.diagnostics.geometry_contract import (
    GeometrySample,
    GeometryVerdict,
    verify_geometry_contract,
)

CALIBRATION_VERSION = "v1.1"
SCORING_SURFACE_CALIBRATION = "S_final_v1.1"
DEFAULT_CALIBRATION_PATH = Path(".persona_ai/calibration_field.json")

SENSITIVITY_ALPHA = 0.35
MIN_CLUSTER_STD = 0.08
TARGET_SPREAD_STD = 0.12
MAX_CALIBRATION_DELTA = 0.15
STABILITY_DAMPING = 0.85


@dataclass
class ClusterStats:
    fp_id: str
    count: int = 0
    mean: float = 0.5
    m2: float = 0.0

    @property
    def std(self) -> float:
        if self.count < 2:
            return MIN_CLUSTER_STD
        return max(MIN_CLUSTER_STD, math.sqrt(self.m2 / self.count))

    def update(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    def to_dict(self) -> dict[str, Any]:
        return {"fp_id": self.fp_id, "count": self.count, "mean": round(self.mean, 4), "std": round(self.std, 4)}


@dataclass
class CalibrationResult:
    s_final_raw: float
    s_calibrated: float
    calibration_scale: float
    calibration_delta: float
    cluster_mean: float
    cluster_std: float
    fp_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalibratedScore:
    decomp: ScoreDecomposition
    calibration: CalibrationResult
    s_arbitration: float
    fast_path_eligible: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "decomp": self.decomp.to_dict(),
            "calibration": self.calibration.to_dict(),
            "s_arbitration": self.s_arbitration,
            "fast_path_eligible": self.fast_path_eligible,
        }


class CalibrationFieldStore:
    """Per-fingerprint cluster statistics for normalization field."""

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_CALIBRATION_PATH
        self.clusters: dict[str, ClusterStats] = {}
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        for fp_id, row in raw.get("clusters", {}).items():
            self.clusters[fp_id] = ClusterStats(
                fp_id=fp_id,
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
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def stats_for(self, fp_id: str) -> ClusterStats:
        if fp_id not in self.clusters:
            self.clusters[fp_id] = ClusterStats(fp_id=fp_id)
        return self.clusters[fp_id]

    def observe(self, fp_id: str, s_raw: float, *, persist: bool = False) -> ClusterStats:
        stats = self.stats_for(fp_id)
        stats.update(s_raw)
        if persist:
            self.save()
        return stats


def calibrate_s_final(
    s_raw: float,
    *,
    fp_id: str,
    cluster_mean: float,
    cluster_std: float,
) -> CalibrationResult:
    """Sensitivity-preserving monotonic calibration with stability guard."""
    effective_std = max(cluster_std, MIN_CLUSTER_STD)

    if effective_std < TARGET_SPREAD_STD:
        stretch = 1.0 + SENSITIVITY_ALPHA * (TARGET_SPREAD_STD - effective_std) / TARGET_SPREAD_STD
    else:
        stretch = 1.0

    stretched = cluster_mean + (s_raw - cluster_mean) * stretch
    raw_delta = stretched - s_raw
    damped_delta = raw_delta * STABILITY_DAMPING
    clamped_delta = max(-MAX_CALIBRATION_DELTA, min(MAX_CALIBRATION_DELTA, damped_delta))
    s_cal = round(max(0.0, min(1.0, s_raw + clamped_delta)), 4)

    return CalibrationResult(
        s_final_raw=s_raw,
        s_calibrated=s_cal,
        calibration_scale=round(stretch, 4),
        calibration_delta=round(clamped_delta, 4),
        cluster_mean=round(cluster_mean, 4),
        cluster_std=round(effective_std, 4),
        fp_id=fp_id,
    )


def apply_surface_calibration(
    decomp: ScoreDecomposition,
    *,
    fp_id: str,
    store: CalibrationFieldStore | None = None,
    persist_stats: bool = False,
    use_calibrated_for_fast_path: bool = True,
) -> CalibratedScore:
    """Apply normalization field; scalar contract on decomp remains valid."""
    field_store = store or CalibrationFieldStore()
    stats = field_store.stats_for(fp_id)
    cal = calibrate_s_final(
        decomp.s_final,
        fp_id=fp_id,
        cluster_mean=stats.mean,
        cluster_std=stats.std,
    )
    field_store.observe(fp_id, decomp.s_final, persist=persist_stats)

    s_arbitration = cal.s_calibrated if use_calibrated_for_fast_path else decomp.s_final
    attempts_ok = decomp.effective_attempts >= 2.0
    eligible = (
        attempts_ok
        and s_arbitration >= decomp.threshold
        and decomp.trust_state == "active"
        and decomp.contract_valid
    )

    return CalibratedScore(
        decomp=decomp,
        calibration=cal,
        s_arbitration=s_arbitration,
        fast_path_eligible=eligible,
    )


def calibrate_batch(
    items: list[tuple[str, str, ScoreDecomposition]],
    *,
    store: CalibrationFieldStore | None = None,
    persist: bool = False,
) -> tuple[list[CalibratedScore], GeometryVerdict]:
    """Calibrate a batch and verify geometry contract."""
    results: list[CalibratedScore] = []
    for fp_id, _patch_id, decomp in items:
        results.append(
            apply_surface_calibration(decomp, fp_id=fp_id, store=store, persist_stats=False)
        )
    if persist and store:
        store.save()

    geo_samples = [
        GeometrySample(
            fp_id=r.calibration.fp_id,
            patch_id=items[i][1],
            s_final_raw=r.calibration.s_final_raw,
            s_final_calibrated=r.calibration.s_calibrated,
        )
        for i, r in enumerate(results)
    ]
    verdict = verify_geometry_contract(geo_samples)
    return results, verdict


def format_calibration_trace(cal: CalibratedScore) -> str:
    c = cal.calibration
    d = cal.decomp
    return (
        f"  S_raw={c.s_final_raw:.3f} -> S_cal={c.s_calibrated:.3f} "
        f"(delta={c.calibration_delta:+.3f} scale={c.calibration_scale:.2f}) "
        f"cluster mean={c.cluster_mean:.2f} std={c.cluster_std:.2f} "
        f"arbitration={cal.s_arbitration:.3f} eligible={cal.fast_path_eligible} "
        f"contract={'ok' if d.contract_valid else 'FAIL'}"
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    from persona_ai.diagnostics.fast_path_controller import compute_S_final

    parser = argparse.ArgumentParser(description="Surface calibration v1.1 preview")
    parser.add_argument("--fp-id", default="fp_demo")
    parser.add_argument("--raw-score", type=float, default=0.82)
    parser.add_argument("--learned-score", type=float, default=0.75)
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    store = CalibrationFieldStore()
    decomp = compute_S_final(
        raw_score=args.raw_score,
        learned_score=args.learned_score,
        elasticity_weight=1.0,
        decay_factor=1.0,
        trust_state="active",
    )
    cal = apply_surface_calibration(decomp, fp_id=args.fp_id, store=store, persist_stats=args.persist)

    if args.json:
        print(json.dumps(cal.to_dict(), indent=2))
    else:
        print(f"=== Surface Calibration | {CALIBRATION_VERSION} ===")
        print(format_calibration_trace(cal))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
