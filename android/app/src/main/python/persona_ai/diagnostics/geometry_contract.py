"""S_final Geometry Contract v1 — distribution invariants for informative scoring space.

Scalar contract guarantees correctness; geometry contract guarantees
the score field remains discriminative (not collapsed / saturated).
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

GEOMETRY_CONTRACT_VERSION = "v1"

MIN_BATCH_SIZE = 2
MIN_SPREAD_STD = 0.04
MAX_SATURATION_RATE = 0.75
MAX_COLLAPSE_BAND_RATE = 0.90
COLLAPSE_BAND = (0.55, 0.92)
SATURATION_FLOOR = 0.85
MIN_RANK_PRESERVATION = 1.0


@dataclass
class GeometrySample:
    fp_id: str
    patch_id: str
    s_final_raw: float
    s_final_calibrated: float | None = None

    @property
    def s_effective(self) -> float:
        return self.s_final_calibrated if self.s_final_calibrated is not None else self.s_final_raw


@dataclass
class GeometryViolation:
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GeometryVerdict:
    valid: bool
    spread_std: float
    saturation_rate: float
    collapse_band_rate: float
    rank_preservation: float
    violations: list[GeometryViolation]
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "geometry_contract_version": GEOMETRY_CONTRACT_VERSION,
            "spread_std": self.spread_std,
            "saturation_rate": self.saturation_rate,
            "collapse_band_rate": self.collapse_band_rate,
            "rank_preservation": self.rank_preservation,
            "sample_count": self.sample_count,
            "violations": [v.to_dict() for v in self.violations],
        }


def _rank(values: list[float]) -> list[int]:
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0] * len(values)
    for rank, (idx, _) in enumerate(indexed):
        ranks[idx] = rank
    return ranks


def rank_preservation(raw: list[float], calibrated: list[float]) -> float:
    if len(raw) < 2:
        return 1.0
    r_raw = _rank(raw)
    r_cal = _rank(calibrated)
    matches = sum(1 for a, b in zip(r_raw, r_cal) if a == b)
    return round(matches / len(raw), 3)


def verify_geometry_contract(samples: list[GeometrySample]) -> GeometryVerdict:
    """Verify batch-level S_final distribution health."""
    violations: list[GeometryViolation] = []
    n = len(samples)

    if n < MIN_BATCH_SIZE:
        return GeometryVerdict(
            valid=True,
            spread_std=0.0,
            saturation_rate=0.0,
            collapse_band_rate=0.0,
            rank_preservation=1.0,
            violations=[],
            sample_count=n,
        )

    effective = [s.s_effective for s in samples]
    raw = [s.s_final_raw for s in samples]
    calibrated = [s.s_effective for s in samples]

    spread = round(statistics.pstdev(effective), 4) if n > 1 else 0.0
    sat_rate = round(sum(1 for v in effective if v >= SATURATION_FLOOR) / n, 3)
    collapse_rate = round(
        sum(1 for v in effective if COLLAPSE_BAND[0] <= v <= COLLAPSE_BAND[1]) / n, 3
    )
    rank_pres = rank_preservation(raw, calibrated)

    if spread < MIN_SPREAD_STD:
        violations.append(
            GeometryViolation(
                code="DISTRIBUTION_COLLAPSE",
                message=f"score spread std={spread} below minimum {MIN_SPREAD_STD}",
                detail={"spread_std": spread, "min_required": MIN_SPREAD_STD},
            )
        )
    if sat_rate > MAX_SATURATION_RATE:
        violations.append(
            GeometryViolation(
                code="SATURATION_DOMINANCE",
                message=f"{sat_rate:.0%} scores >= {SATURATION_FLOOR} (max {MAX_SATURATION_RATE:.0%})",
                detail={"saturation_rate": sat_rate},
            )
        )
    if collapse_rate > MAX_COLLAPSE_BAND_RATE:
        violations.append(
            GeometryViolation(
                code="MIDDLE_BAND_COLLAPSE",
                message=f"{collapse_rate:.0%} scores in dead band {COLLAPSE_BAND}",
                detail={"collapse_band_rate": collapse_rate},
            )
        )
    if rank_pres < MIN_RANK_PRESERVATION and any(s.s_final_calibrated is not None for s in samples):
        violations.append(
            GeometryViolation(
                code="RANK_INVERSION",
                message="calibration broke rank preservation",
                detail={"rank_preservation": rank_pres},
            )
        )

    return GeometryVerdict(
        valid=len(violations) == 0,
        spread_std=spread,
        saturation_rate=sat_rate,
        collapse_band_rate=collapse_rate,
        rank_preservation=rank_pres,
        violations=violations,
        sample_count=n,
    )


def format_geometry_verdict(verdict: GeometryVerdict) -> str:
    status = "HEALTHY" if verdict.valid else "GEOMETRY_VIOLATION"
    lines = [
        f"=== S_final Geometry Contract | {GEOMETRY_CONTRACT_VERSION} ===",
        f"  status: {status} | n={verdict.sample_count}",
        f"  spread_std={verdict.spread_std:.4f} saturation={verdict.saturation_rate:.0%} "
        f"collapse_band={verdict.collapse_band_rate:.0%} rank_pres={verdict.rank_preservation:.2f}",
    ]
    for v in verdict.violations:
        lines.append(f"  [VIOLATION:{v.code}] {v.message}")
    return "\n".join(lines)
