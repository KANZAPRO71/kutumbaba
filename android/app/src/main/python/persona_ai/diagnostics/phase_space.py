"""Phase Space Identity v1.1 — topology / semantic family / comparability frames.

Separates:
  topology_id          structural + schema + energy topology
  semantic_family_id   role topology only (does NOT trigger generation breaks)
  manifold_generation_id = hash(topology_id)

HARD frame: exact CI lattice identity (fixture hash + version equality)
SOFT frame: manifold family dynamics (generation id, ignores fixture hash)
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from persona_ai.diagnostics.constraint_arbitration import ARBITRATION_VERSION
from persona_ai.diagnostics.cross_cluster_calibration import (
    CALIBRATION_VERSION,
    semantic_cluster_key,
)
from persona_ai.diagnostics.explainability_contract import (
    CONTRACT_VERSION,
    RECONSTRUCTION_EPSILON,
    SCORING_SURFACE_VERSION,
)
from persona_ai.diagnostics.geometry_ci_gate import GATE_VERSION
from persona_ai.diagnostics.geometry_contract import GEOMETRY_CONTRACT_VERSION

PHASE_SPACE_VERSION = "v1.1"
CONSTRAINT_ENERGY_SCHEMA = "v1"
MANIFOLD_CI_VERSION = "v1"

ComparabilityClass = Literal["HARD", "SOFT", "GENESIS"]
SnapshotSource = Literal["ci", "runtime", "smoke"]


@dataclass(frozen=True)
class TopologyIdentity:
    scoring_surface_version: str
    geometry_contract_version: str
    geometry_gate_version: str
    calibration_version: str
    arbitration_version: str
    constraint_energy_schema: str
    explainability_contract_version: str
    manifold_ci_version: str

    def to_canonical_dict(self) -> dict[str, str]:
        return {
            "scoring_surface_version": self.scoring_surface_version,
            "geometry_contract_version": self.geometry_contract_version,
            "geometry_gate_version": self.geometry_gate_version,
            "calibration_version": self.calibration_version,
            "arbitration_version": self.arbitration_version,
            "constraint_energy_schema": self.constraint_energy_schema,
            "explainability_contract_version": self.explainability_contract_version,
            "manifold_ci_version": self.manifold_ci_version,
        }


def current_topology_identity() -> TopologyIdentity:
    return TopologyIdentity(
        scoring_surface_version=SCORING_SURFACE_VERSION,
        geometry_contract_version=GEOMETRY_CONTRACT_VERSION,
        geometry_gate_version=GATE_VERSION,
        calibration_version=CALIBRATION_VERSION,
        arbitration_version=ARBITRATION_VERSION,
        constraint_energy_schema=CONSTRAINT_ENERGY_SCHEMA,
        explainability_contract_version=CONTRACT_VERSION,
        manifold_ci_version=MANIFOLD_CI_VERSION,
    )


def compute_topology_id(topology: TopologyIdentity | None = None) -> str:
    """Structural identity — bumps only on schema / energy topology change."""
    payload = json.dumps((topology or current_topology_identity()).to_canonical_dict(), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def semantic_equivalence_class(semantic_by_fp: dict[str, str]) -> str:
    """Role topology — sorted unique semantic cluster keys."""
    clusters = sorted({semantic_cluster_key(key) for key in semantic_by_fp.values()})
    return "|".join(clusters) if clusters else "unknown"


def compute_semantic_family_id(semantic_by_fp: dict[str, str]) -> str:
    """Semantic family hash — tracked but does NOT break generation."""
    payload = semantic_equivalence_class(semantic_by_fp)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def compute_manifold_generation_id(topology: TopologyIdentity | None = None) -> str:
    """Topological partition — hash(topology_id) only, not semantic."""
    return f"gen_{compute_topology_id(topology)}"


def compute_fixture_hash(
    semantic_by_fp: dict[str, str],
    *,
    score_params: list[dict[str, float | str]] | None = None,
) -> str:
    """Exact CI lattice point identity."""
    payload = {
        "semantic_by_fp": semantic_by_fp,
        "score_params": score_params or [],
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class PhaseSnapshotIdentity:
    topology_id: str
    semantic_family_id: str
    manifold_generation_id: str
    semantic_equivalence_class: str
    canonical_fixture_hash: str
    scoring_surface_version: str
    geometry_gate_version: str
    arbitration_version: str
    source: SnapshotSource
    comparability_class: ComparabilityClass
    parent_generation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TensionVector:
    scalar_residual: float
    geometry_residual: float
    separation_residual: float
    coupling_residual: float
    equilibrium_residual: float
    constraint_anisotropy: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @property
    def norm(self) -> float:
        components = [
            self.scalar_residual,
            self.geometry_residual,
            self.separation_residual,
            self.coupling_residual,
            self.equilibrium_residual,
        ]
        return round(math.sqrt(sum(value * value for value in components)), 6)


def compute_constraint_anisotropy(tension: TensionVector) -> float:
    """Variance of tension components — detects redistribution vs true stability."""
    components = [
        tension.scalar_residual,
        tension.geometry_residual,
        tension.separation_residual,
        tension.coupling_residual,
        tension.equilibrium_residual,
    ]
    if not components:
        return 0.0
    mean = sum(components) / len(components)
    variance = sum((value - mean) ** 2 for value in components) / len(components)
    return round(variance, 6)


@dataclass
class PhaseVector:
    reconstruction_delta: float
    spread_std: float
    score_entropy: float
    min_cluster_distance: float
    coupling_asymmetry: float
    coupling_stress_rate: float
    e_total: float
    energy_ratio_scalar: float
    energy_ratio_geometry: float
    projection_iterations: int
    gate_pass: float
    arb_feasible: float

    def to_list(self) -> list[float]:
        return [
            self.reconstruction_delta,
            self.spread_std,
            self.score_entropy,
            self.min_cluster_distance,
            self.coupling_asymmetry,
            self.coupling_stress_rate,
            self.e_total,
            self.energy_ratio_scalar,
            self.energy_ratio_geometry,
            float(self.projection_iterations),
            self.gate_pass,
            self.arb_feasible,
        ]

    def normalized(self) -> list[float]:
        from persona_ai.diagnostics.geometry_ci_gate import (
            MAX_COUPLING_ASYMMETRY,
            MIN_INTER_CLUSTER_DISTANCE,
            MIN_SCORE_ENTROPY,
        )
        from persona_ai.diagnostics.geometry_contract import MIN_SPREAD_STD

        e_total = max(self.e_total, 0.0)
        return [
            self.reconstruction_delta / RECONSTRUCTION_EPSILON,
            self.spread_std / MIN_SPREAD_STD if MIN_SPREAD_STD else self.spread_std,
            self.score_entropy / MIN_SCORE_ENTROPY if MIN_SCORE_ENTROPY else self.score_entropy,
            self.min_cluster_distance / MIN_INTER_CLUSTER_DISTANCE
            if MIN_INTER_CLUSTER_DISTANCE
            else self.min_cluster_distance,
            self.coupling_asymmetry / MAX_COUPLING_ASYMMETRY
            if MAX_COUPLING_ASYMMETRY
            else self.coupling_asymmetry,
            self.coupling_stress_rate,
            math.log1p(e_total),
            self.energy_ratio_scalar,
            self.energy_ratio_geometry,
            float(self.projection_iterations),
            self.gate_pass,
            self.arb_feasible,
        ]

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def soft_phase_distance(a: PhaseVector, b: PhaseVector) -> float:
    """Weighted L2 on normalized phase coordinates — SOFT frame metric."""
    norm_a = a.normalized()
    norm_b = b.normalized()
    if len(norm_a) != len(norm_b):
        return float("inf")
    return round(math.sqrt(sum((x - y) ** 2 for x, y in zip(norm_a, norm_b))), 6)


@dataclass
class PhaseSnapshot:
    snapshot_id: str
    timestamp: str
    identity: PhaseSnapshotIdentity
    phase: PhaseVector
    tension: TensionVector
    feasible_volume_proxy: float
    energy_sharpness: float
    ci_exit_code: int
    violation_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_space_version": PHASE_SPACE_VERSION,
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "identity": self.identity.to_dict(),
            "phase": self.phase.to_dict(),
            "tension": self.tension.to_dict(),
            "feasible_volume_proxy": self.feasible_volume_proxy,
            "energy_sharpness": self.energy_sharpness,
            "ci_exit_code": self.ci_exit_code,
            "violation_codes": self.violation_codes,
        }


def hard_comparable(a: PhaseSnapshotIdentity, b: PhaseSnapshotIdentity) -> bool:
    """Exact CI lattice point — fixture hash + strict version equality."""
    return (
        a.source == "ci"
        and b.source == "ci"
        and a.scoring_surface_version == b.scoring_surface_version
        and a.geometry_gate_version == b.geometry_gate_version
        and a.arbitration_version == b.arbitration_version
        and a.canonical_fixture_hash == b.canonical_fixture_hash
    )


def soft_comparable(a: PhaseSnapshotIdentity, b: PhaseSnapshotIdentity) -> bool:
    """Manifold family — ignores fixture hash, uses generation + surface version."""
    return (
        a.manifold_generation_id == b.manifold_generation_id
        and a.scoring_surface_version == b.scoring_surface_version
        and version_band_compatible(a.topology_id, b.topology_id)
    )


def version_band_compatible(topology_id_a: str, topology_id_b: str) -> bool:
    """SOFT frame tolerates identity within same topological partition."""
    return topology_id_a == topology_id_b


def build_snapshot_identity(
    *,
    semantic_by_fp: dict[str, str],
    canonical_fixture_hash: str,
    source: SnapshotSource,
    comparability_class: ComparabilityClass,
    score_params: list[dict[str, float | str]] | None = None,
    parent_generation_id: str | None = None,
    topology: TopologyIdentity | None = None,
) -> PhaseSnapshotIdentity:
    topology = topology or current_topology_identity()
    fixture_hash = canonical_fixture_hash
    if not fixture_hash and score_params is not None:
        fixture_hash = compute_fixture_hash(semantic_by_fp, score_params=score_params)
    sem_class = semantic_equivalence_class(semantic_by_fp)
    return PhaseSnapshotIdentity(
        topology_id=compute_topology_id(topology),
        semantic_family_id=compute_semantic_family_id(semantic_by_fp),
        manifold_generation_id=compute_manifold_generation_id(topology),
        semantic_equivalence_class=sem_class,
        canonical_fixture_hash=fixture_hash,
        scoring_surface_version=topology.scoring_surface_version,
        geometry_gate_version=topology.geometry_gate_version,
        arbitration_version=topology.arbitration_version,
        source=source,
        comparability_class=comparability_class,
        parent_generation_id=parent_generation_id,
    )
