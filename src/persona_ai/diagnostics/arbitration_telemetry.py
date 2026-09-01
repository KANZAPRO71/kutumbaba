"""Arbitration Telemetry Store v1 — phase-space recorder (Phase A: CI lattice)."""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from persona_ai.diagnostics.explainability_contract import (
    RECONSTRUCTION_EPSILON,
    verify_explainability_contract,
)
from persona_ai.diagnostics.geometry_ci_gate import (
    MAX_COUPLING_ASYMMETRY,
    MIN_INTER_CLUSTER_DISTANCE,
    MIN_SCORE_ENTROPY,
)
from persona_ai.diagnostics.geometry_contract import MIN_SPREAD_STD
from persona_ai.diagnostics.manifold_ci import CANONICAL_SEMANTIC, CanonicalFixture, build_canonical_fixture
from persona_ai.diagnostics.phase_space import (
    PHASE_SPACE_VERSION,
    PhaseSnapshot,
    PhaseVector,
    TensionVector,
    build_snapshot_identity,
    compute_constraint_anisotropy,
    compute_fixture_hash,
)

DEFAULT_TELEMETRY_PATH = Path(".persona_ai/arbitration_telemetry.json")
MAX_SNAPSHOTS = 200

CANONICAL_SCORE_PARAMS = [
    {"fp_id": "fp_a", "raw_score": 0.52, "learned_score": 0.48, "elasticity": 1.0, "decay": 1.0},
    {"fp_id": "fp_b", "raw_score": 0.38, "learned_score": 0.42, "elasticity": 1.0, "decay": 1.0},
    {"fp_id": "fp_c", "raw_score": 0.71, "learned_score": 0.68, "elasticity": 0.95, "decay": 1.0},
]


def _canonical_fixture_hash() -> str:
    return compute_fixture_hash(CANONICAL_SEMANTIC, score_params=CANONICAL_SCORE_PARAMS)


def _tension_from_fixture(fixture: CanonicalFixture) -> TensionVector:
    gate = fixture.geometry_gate
    sep = gate.separation if gate else None
    max_recon = 0.0
    for decomp in fixture.decomps:
        verdict = verify_explainability_contract(decomp)
        if verdict.reconstruction_delta is not None:
            max_recon = max(max_recon, verdict.reconstruction_delta)

    spread = gate.base_geometry.spread_std if gate else 0.0
    min_dist = sep.min_cluster_distance if sep else 1.0
    asymmetry = sep.coupling_asymmetry if sep else 0.0
    e_total = 0.0
    if fixture.arbitration and fixture.arbitration.results:
        e_total = sum(result.energy.e_total for result in fixture.arbitration.results) / len(
            fixture.arbitration.results
        )

    tension = TensionVector(
        scalar_residual=round(max_recon / RECONSTRUCTION_EPSILON, 4),
        geometry_residual=round(max(0.0, (MIN_SPREAD_STD - spread) / MIN_SPREAD_STD), 4)
        if MIN_SPREAD_STD
        else 0.0,
        separation_residual=round(
            max(0.0, (MIN_INTER_CLUSTER_DISTANCE - min_dist) / MIN_INTER_CLUSTER_DISTANCE), 4
        )
        if MIN_INTER_CLUSTER_DISTANCE
        else 0.0,
        coupling_residual=round(asymmetry / MAX_COUPLING_ASYMMETRY, 4) if MAX_COUPLING_ASYMMETRY else 0.0,
        equilibrium_residual=round(math.log1p(max(e_total, 0.0)), 4),
    )
    tension.constraint_anisotropy = compute_constraint_anisotropy(tension)
    return tension


def _phase_from_fixture(fixture: CanonicalFixture) -> PhaseVector:
    gate = fixture.geometry_gate
    sep = gate.separation if gate else None
    max_recon = 0.0
    for decomp in fixture.decomps:
        verdict = verify_explainability_contract(decomp)
        if verdict.reconstruction_delta is not None:
            max_recon = max(max_recon, verdict.reconstruction_delta)

    e_total = 0.0
    e_scalar = 0.0
    e_geometry = 0.0
    if fixture.arbitration and fixture.arbitration.results:
        results = fixture.arbitration.results
        e_total = sum(result.energy.e_total for result in results) / len(results)
        e_scalar = sum(result.energy.e_scalar for result in results) / len(results)
        e_geometry = sum(result.energy.e_geometry for result in results) / len(results)

    denom = e_total if e_total > 0 else 1.0
    return PhaseVector(
        reconstruction_delta=round(max_recon, 6),
        spread_std=gate.base_geometry.spread_std if gate else 0.0,
        score_entropy=sep.score_entropy if sep else 0.0,
        min_cluster_distance=sep.min_cluster_distance if sep else 0.0,
        coupling_asymmetry=sep.coupling_asymmetry if sep else 0.0,
        coupling_stress_rate=sep.coupling_stress_rate if sep else 0.0,
        e_total=round(e_total, 6),
        energy_ratio_scalar=round(e_scalar / denom, 4),
        energy_ratio_geometry=round(e_geometry / denom, 4),
        projection_iterations=0,
        gate_pass=1.0 if gate and gate.pass_gate else 0.0,
        arb_feasible=1.0 if fixture.arbitration and fixture.arbitration.batch_feasible else 0.0,
    )


def build_ci_phase_snapshot(
    fixture: CanonicalFixture | None = None,
    *,
    ci_exit_code: int = 0,
    violation_codes: list[str] | None = None,
    commit_sha: str | None = None,
) -> PhaseSnapshot:
    """Build HARD-frame CI lattice snapshot from canonical fixture."""
    fixture = fixture or build_canonical_fixture()
    gate = fixture.geometry_gate
    sep = gate.separation if gate else None
    phase = _phase_from_fixture(fixture)
    tension = _tension_from_fixture(fixture)

    spread = phase.spread_std
    entropy = phase.score_entropy
    min_dist = phase.min_cluster_distance
    feasible_volume = round(spread * entropy * min_dist, 6)
    n_results = len(fixture.arbitration.results) if fixture.arbitration else 1
    energy_sharpness = round(phase.e_total / max(n_results, 1), 6)

    identity = build_snapshot_identity(
        semantic_by_fp=CANONICAL_SEMANTIC,
        canonical_fixture_hash=_canonical_fixture_hash(),
        source="ci",
        comparability_class="HARD",
        score_params=CANONICAL_SCORE_PARAMS,
    )

    codes = list(violation_codes or [])
    if gate and not gate.pass_gate:
        codes.extend(v.code for v in gate.violations)

    return PhaseSnapshot(
        snapshot_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        identity=identity,
        phase=phase,
        tension=tension,
        feasible_volume_proxy=feasible_volume,
        energy_sharpness=energy_sharpness,
        ci_exit_code=ci_exit_code,
        violation_codes=sorted(set(codes)),
    )


@dataclass
class ArbitrationTelemetryStore:
    path: Path = field(default_factory=lambda: DEFAULT_TELEMETRY_PATH)
    snapshots: list[PhaseSnapshot] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        from persona_ai.diagnostics.phase_space import PhaseSnapshotIdentity

        for row in raw.get("snapshots", []):
            identity = PhaseSnapshotIdentity(**row["identity"])
            phase = PhaseVector(**row["phase"])
            tension = TensionVector(**row["tension"])
            self.snapshots.append(
                PhaseSnapshot(
                    snapshot_id=row["snapshot_id"],
                    timestamp=row["timestamp"],
                    identity=identity,
                    phase=phase,
                    tension=tension,
                    feasible_volume_proxy=row["feasible_volume_proxy"],
                    energy_sharpness=row["energy_sharpness"],
                    ci_exit_code=row.get("ci_exit_code", 0),
                    violation_codes=row.get("violation_codes", []),
                )
            )

    def append(self, snapshot: PhaseSnapshot) -> None:
        self.snapshots.append(snapshot)
        if len(self.snapshots) > MAX_SNAPSHOTS:
            self.snapshots = self.snapshots[-MAX_SNAPSHOTS:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "telemetry_version": PHASE_SPACE_VERSION,
            "snapshots": [snapshot.to_dict() for snapshot in self.snapshots],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def latest_ci_snapshot(self) -> PhaseSnapshot | None:
        for snapshot in reversed(self.snapshots):
            if snapshot.identity.source == "ci" and snapshot.identity.comparability_class == "HARD":
                return snapshot
        return None

    def get_snapshot_by_id(self, snapshot_id: str) -> PhaseSnapshot | None:
        for snapshot in self.snapshots:
            if snapshot.snapshot_id == snapshot_id:
                return snapshot
        return None

    def record_ci_lattice(
        self,
        fixture: CanonicalFixture | None = None,
        *,
        ci_exit_code: int = 0,
        violation_codes: list[str] | None = None,
        persist: bool = True,
    ) -> PhaseSnapshot:
        snapshot = build_ci_phase_snapshot(
            fixture, ci_exit_code=ci_exit_code, violation_codes=violation_codes
        )
        self.append(snapshot)
        if persist:
            self.save()
        return snapshot


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Arbitration phase-space telemetry")
    parser.add_argument("--record-ci", action="store_true", help="Record CI lattice snapshot")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--telemetry", type=Path, default=DEFAULT_TELEMETRY_PATH)
    args = parser.parse_args(argv)

    store = ArbitrationTelemetryStore(args.telemetry)
    if args.record_ci:
        snapshot = store.record_ci_lattice(persist=True)
        if args.json:
            print(json.dumps(snapshot.to_dict(), indent=2))
        else:
            print(f"Recorded CI lattice snapshot {snapshot.snapshot_id}")
            print(f"  generation={snapshot.identity.manifold_generation_id}")
            print(f"  semantic_family={snapshot.identity.semantic_family_id}")
            print(f"  fixture_hash={snapshot.identity.canonical_fixture_hash}")
        return 0

    latest = store.latest_ci_snapshot()
    if args.json:
        print(json.dumps(latest.to_dict() if latest else {}, indent=2))
    else:
        if latest:
            print(f"Latest CI snapshot: {latest.snapshot_id} @ {latest.timestamp}")
            print(f"  generation={latest.identity.manifold_generation_id}")
            print(f"  tension_norm={latest.tension.norm} anisotropy={latest.tension.constraint_anisotropy}")
        else:
            print("No CI lattice snapshots recorded yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
