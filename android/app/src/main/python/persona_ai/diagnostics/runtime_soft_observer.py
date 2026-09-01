"""Runtime SOFT observer v1 — online dynamical system observer (Phase C).

Strict observer layer: does NOT modify arbitration, CI, or generation_id.
Emits compressed SOFT snapshots anchored to nearest CI lattice point.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from persona_ai.diagnostics.arbitration_telemetry import ArbitrationTelemetryStore
from persona_ai.diagnostics.constraint_arbitration import BatchArbitrationVerdict
from persona_ai.diagnostics.cross_cluster_calibration import CrossClusterCalibrationResult
from persona_ai.diagnostics.explainability_contract import (
    RECONSTRUCTION_EPSILON,
    verify_explainability_contract,
)
from persona_ai.diagnostics.geometry_ci_gate import (
    GeometryGateVerdict,
    MAX_COUPLING_ASYMMETRY,
    MIN_INTER_CLUSTER_DISTANCE,
)
from persona_ai.diagnostics.geometry_contract import MIN_SPREAD_STD
from persona_ai.diagnostics.invariance_classifier import (
    InvariantClass,
    classify_snapshot,
    classify_transition,
)
from persona_ai.diagnostics.phase_space import (
    PHASE_SPACE_VERSION,
    PhaseSnapshot,
    PhaseSnapshotIdentity,
    PhaseVector,
    TensionVector,
    build_snapshot_identity,
    compute_constraint_anisotropy,
    soft_comparable,
    soft_phase_distance,
)
from persona_ai.diagnostics.surface_calibration import CalibratedScore

OBSERVER_VERSION = "v1.2"
DEFAULT_RUNTIME_PATH = Path(".persona_ai/runtime_soft_telemetry.json")
MAX_RUNTIME_SNAPSHOTS = 500
MAX_OBSERVER_EVENTS = 1000

GenerationSource = Literal["ci_anchor", "runtime_inferred"]

TAU_STABLE = 0.08
TAU_DRIFT = 0.35
ANISOTROPY_SPIKE = 0.08
BOUNDARY_SUGGESTION_THRESHOLD = 3
TAU_BIAS = 0.70
ANCHOR_DENSITY_LAMBDA = 0.5
ANCHOR_DENSITY_RADIUS = 0.15


@dataclass
class ObserverEvent:
    """Internal event log for independence diagnostics — not phase state."""

    timestamp: str
    fp_id: str
    stored: bool
    invariant_class: str
    regime_changed: bool
    compression_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ObserverDiagnostics:
    observer_independence_score: float
    compression_regime_correlation: float
    bias_warning: bool
    event_count: int
    anchor_density_mean: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FrozenGenerationIdentity:
    """Inertial frame label frozen at SOFT snapshot emission — never recomputed."""

    manifold_generation_id: str
    generation_source: GenerationSource
    generation_anchor_snapshot_id: str | None


@dataclass
class SoftSnapshot:
    snapshot_id: str
    timestamp: str
    fp_id: str
    patch_id: str
    s_final: float
    s_calibrated: float
    s_arbitration: float
    phase_norm: list[float]
    tension: TensionVector
    projection_iterations: int
    gate_pass: bool
    gate_admitted: bool
    nearest_ci_lattice_snapshot_id: str | None
    soft_distance_to_anchor: float
    invariant_class: str
    manifold_generation_id: str
    generation_source: GenerationSource
    generation_anchor_snapshot_id: str | None
    soft_distance_effective: float = 0.0
    anchor_density: float = 0.0
    transition_label: str | None = None
    structural_drift_flag: bool = False
    ci_fixture_review_suggested: bool = False
    trigger_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observer_version": OBSERVER_VERSION,
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "fp_id": self.fp_id,
            "patch_id": self.patch_id,
            "s_final": self.s_final,
            "s_calibrated": self.s_calibrated,
            "s_arbitration": self.s_arbitration,
            "phase_norm": self.phase_norm,
            "tension": self.tension.to_dict(),
            "projection_iterations": self.projection_iterations,
            "gate_pass": self.gate_pass,
            "gate_admitted": self.gate_admitted,
            "nearest_ci_lattice_snapshot_id": self.nearest_ci_lattice_snapshot_id,
            "soft_distance_to_anchor": self.soft_distance_to_anchor,
            "soft_distance_effective": self.soft_distance_effective,
            "anchor_density": self.anchor_density,
            "invariant_class": self.invariant_class,
            "manifold_generation_id": self.manifold_generation_id,
            "generation_source": self.generation_source,
            "generation_anchor_snapshot_id": self.generation_anchor_snapshot_id,
            "transition_label": self.transition_label,
            "structural_drift_flag": self.structural_drift_flag,
            "ci_fixture_review_suggested": self.ci_fixture_review_suggested,
            "trigger_flags": self.trigger_flags,
        }


def _batch_tension(
    gate_verdict: GeometryGateVerdict | None,
    arbitration: BatchArbitrationVerdict,
    max_recon: float,
) -> TensionVector:
    sep = gate_verdict.separation if gate_verdict else None
    spread = gate_verdict.base_geometry.spread_std if gate_verdict else 0.0
    min_dist = sep.min_cluster_distance if sep else 1.0
    asymmetry = sep.coupling_asymmetry if sep else 0.0
    e_total = 0.0
    if arbitration.results:
        e_total = sum(result.energy.e_total for result in arbitration.results) / len(arbitration.results)

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


def _batch_phase(
    gate_verdict: GeometryGateVerdict | None,
    arbitration: BatchArbitrationVerdict,
    max_recon: float,
) -> PhaseVector:
    sep = gate_verdict.separation if gate_verdict else None
    e_total = 0.0
    e_scalar = 0.0
    e_geometry = 0.0
    if arbitration.results:
        results = arbitration.results
        e_total = sum(result.energy.e_total for result in results) / len(results)
        e_scalar = sum(result.energy.e_scalar for result in results) / len(results)
        e_geometry = sum(result.energy.e_geometry for result in results) / len(results)
    denom = e_total if e_total > 0 else 1.0

    return PhaseVector(
        reconstruction_delta=round(max_recon, 6),
        spread_std=gate_verdict.base_geometry.spread_std if gate_verdict else 0.0,
        score_entropy=sep.score_entropy if sep else 0.0,
        min_cluster_distance=sep.min_cluster_distance if sep else 0.0,
        coupling_asymmetry=sep.coupling_asymmetry if sep else 0.0,
        coupling_stress_rate=sep.coupling_stress_rate if sep else 0.0,
        e_total=round(e_total, 6),
        energy_ratio_scalar=round(e_scalar / denom, 4),
        energy_ratio_geometry=round(e_geometry / denom, 4),
        projection_iterations=0,
        gate_pass=1.0 if gate_verdict and gate_verdict.pass_gate else 0.0,
        arb_feasible=1.0 if arbitration.batch_feasible else 0.0,
    )


def _runtime_phase_snapshot(
    *,
    semantic_by_fp: dict[str, str],
    fp_id: str,
    phase: PhaseVector,
    tension: TensionVector,
    feasible_volume_proxy: float,
    energy_sharpness: float,
    gate_verdict: GeometryGateVerdict | None,
) -> PhaseSnapshot:
    identity = build_snapshot_identity(
        semantic_by_fp=semantic_by_fp,
        canonical_fixture_hash="",
        source="runtime",
        comparability_class="SOFT",
    )
    codes: list[str] = []
    if gate_verdict and not gate_verdict.pass_gate:
        codes.extend(v.code for v in gate_verdict.violations)
    return PhaseSnapshot(
        snapshot_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        identity=identity,
        phase=phase,
        tension=tension,
        feasible_volume_proxy=feasible_volume_proxy,
        energy_sharpness=energy_sharpness,
        ci_exit_code=0,
        violation_codes=codes,
    )


def compute_anchor_density(
    phase: PhaseVector,
    *,
    telemetry: ArbitrationTelemetryStore | None = None,
    radius: float = ANCHOR_DENSITY_RADIUS,
) -> float:
    """Fraction of CI lattice points within radius of query phase."""
    store = telemetry or ArbitrationTelemetryStore()
    ci_snapshots = [
        snapshot
        for snapshot in store.snapshots
        if snapshot.identity.source == "ci" and snapshot.identity.comparability_class == "HARD"
    ]
    if not ci_snapshots:
        return 0.0
    nearby = sum(1 for snapshot in ci_snapshots if soft_phase_distance(phase, snapshot.phase) <= radius)
    return round(nearby / len(ci_snapshots), 4)


def effective_soft_distance(
    d_soft: float,
    anchor_density: float,
    *,
    lam: float = ANCHOR_DENSITY_LAMBDA,
) -> float:
    """Reduce anchoring gravity when CI lattice is dense in local region."""
    if d_soft == float("inf"):
        return d_soft
    return round(d_soft * math.exp(-lam * anchor_density), 6)


def find_nearest_ci_anchor(
    phase: PhaseVector,
    *,
    telemetry: ArbitrationTelemetryStore | None = None,
) -> tuple[str | None, float, float, float]:
    """Map runtime phase to nearest HARD lattice point; return raw and effective d_soft."""
    store = telemetry or ArbitrationTelemetryStore()
    ci_snapshots = [
        snapshot
        for snapshot in store.snapshots
        if snapshot.identity.source == "ci" and snapshot.identity.comparability_class == "HARD"
    ]
    if not ci_snapshots:
        return None, float("inf"), float("inf"), 0.0

    best_id: str | None = None
    best_dist = float("inf")
    for snapshot in ci_snapshots:
        dist = soft_phase_distance(phase, snapshot.phase)
        if dist < best_dist:
            best_dist = dist
            best_id = snapshot.snapshot_id

    density = compute_anchor_density(phase, telemetry=store)
    effective = effective_soft_distance(best_dist, density)
    return best_id, round(best_dist, 6), effective, density


def resolve_frozen_generation_identity(
    *,
    anchor_snapshot_id: str | None,
    runtime_identity: PhaseSnapshotIdentity,
    telemetry: ArbitrationTelemetryStore | None = None,
) -> FrozenGenerationIdentity:
    """Freeze inertial frame at emission — inherit CI anchor generation when available."""
    store = telemetry or ArbitrationTelemetryStore()
    if anchor_snapshot_id:
        anchor = store.get_snapshot_by_id(anchor_snapshot_id)
        if anchor is not None:
            return FrozenGenerationIdentity(
                manifold_generation_id=anchor.identity.manifold_generation_id,
                generation_source="ci_anchor",
                generation_anchor_snapshot_id=anchor_snapshot_id,
            )
    return FrozenGenerationIdentity(
        manifold_generation_id=runtime_identity.manifold_generation_id,
        generation_source="runtime_inferred",
        generation_anchor_snapshot_id=None,
    )


def backfill_soft_generation_identity(
    row: dict[str, Any],
    *,
    telemetry: ArbitrationTelemetryStore | None = None,
) -> FrozenGenerationIdentity:
    """Legacy load: recover frozen frame from persisted fields or CI anchor lookup only."""
    stored_id = row.get("manifold_generation_id") or ""
    if stored_id:
        source = row.get("generation_source", "ci_anchor")
        if source not in ("ci_anchor", "runtime_inferred"):
            source = "ci_anchor"
        return FrozenGenerationIdentity(
            manifold_generation_id=stored_id,
            generation_source=source,  # type: ignore[arg-type]
            generation_anchor_snapshot_id=row.get("generation_anchor_snapshot_id"),
        )

    anchor_id = row.get("nearest_ci_lattice_snapshot_id")
    if anchor_id:
        store = telemetry or ArbitrationTelemetryStore()
        anchor = store.get_snapshot_by_id(anchor_id)
        if anchor is not None:
            return FrozenGenerationIdentity(
                manifold_generation_id=anchor.identity.manifold_generation_id,
                generation_source="ci_anchor",
                generation_anchor_snapshot_id=anchor_id,
            )

    return FrozenGenerationIdentity(
        manifold_generation_id="",
        generation_source="runtime_inferred",
        generation_anchor_snapshot_id=None,
    )


def _pearson_correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return 0.0
    return round(num / (den_x * den_y), 4)


def compute_observer_independence(events: list[ObserverEvent]) -> ObserverDiagnostics:
    """Diagnostic guard: detect self-referential compression ↔ regime coupling."""
    if len(events) < 4:
        return ObserverDiagnostics(
            observer_independence_score=1.0,
            compression_regime_correlation=0.0,
            bias_warning=False,
            event_count=len(events),
            anchor_density_mean=0.0,
        )

    compression_trigger = [1.0 if event.stored else 0.0 for event in events]
    regime_transition = [1.0 if event.regime_changed else 0.0 for event in events]
    corr = _pearson_correlation(compression_trigger, regime_transition)
    independence = round(1.0 - abs(corr), 4)
    return ObserverDiagnostics(
        observer_independence_score=independence,
        compression_regime_correlation=corr,
        bias_warning=abs(corr) >= TAU_BIAS,
        event_count=len(events),
        anchor_density_mean=0.0,
    )


def detect_structural_drift(
    soft_distance: float,
    regime: InvariantClass,
    *,
    use_effective: bool = True,
) -> bool:
    return soft_distance > TAU_DRIFT and regime in (
        InvariantClass.I3_ROTATIONAL,
        InvariantClass.I4_TENSION_ACCUMULATION,
    )


def should_store_snapshot(
    candidate: SoftSnapshot,
    *,
    prev: SoftSnapshot | None,
    prev_regime: InvariantClass | None = None,
) -> tuple[bool, list[str]]:
    """Compression: store only on meaningful phase events."""
    if prev is None:
        return True, ["first_observation"]

    reasons: list[str] = []
    curr_regime = InvariantClass(candidate.invariant_class)

    if prev_regime and curr_regime != prev_regime:
        reasons.append("regime_change")
    if candidate.tension.constraint_anisotropy >= ANISOTROPY_SPIKE:
        if candidate.tension.constraint_anisotropy - prev.tension.constraint_anisotropy >= ANISOTROPY_SPIKE:
            reasons.append("anisotropy_spike")
    if candidate.soft_distance_to_anchor > TAU_STABLE:
        if abs(candidate.soft_distance_to_anchor - prev.soft_distance_to_anchor) > TAU_STABLE:
            reasons.append("anchor_drift")
    if candidate.gate_pass != prev.gate_pass:
        reasons.append("gate_state_flip")
    if candidate.structural_drift_flag:
        reasons.append("structural_deformation")

    return len(reasons) > 0, reasons


def build_soft_snapshot(
    *,
    fp_id: str,
    patch_id: str,
    calibrated_list: list[CalibratedScore],
    cross_results: list[CrossClusterCalibrationResult],
    gate_verdict: GeometryGateVerdict | None,
    arbitration: BatchArbitrationVerdict,
    semantic_by_fp: dict[str, str],
    top_s_final: float,
    top_s_calibrated: float,
    top_s_arbitration: float,
    prev_runtime_phase: PhaseSnapshot | None = None,
    telemetry: ArbitrationTelemetryStore | None = None,
) -> tuple[SoftSnapshot, PhaseSnapshot]:
    max_recon = 0.0
    for cal in calibrated_list:
        verdict = verify_explainability_contract(cal.decomp)
        if verdict.reconstruction_delta is not None:
            max_recon = max(max_recon, verdict.reconstruction_delta)

    phase = _batch_phase(gate_verdict, arbitration, max_recon)
    tension = _batch_tension(gate_verdict, arbitration, max_recon)
    spread = phase.spread_std
    entropy = phase.score_entropy
    min_dist = phase.min_cluster_distance
    feasible_volume = round(spread * entropy * min_dist, 6)
    n_results = len(arbitration.results) if arbitration.results else 1
    energy_sharpness = round(phase.e_total / max(n_results, 1), 6)

    runtime_snap = _runtime_phase_snapshot(
        semantic_by_fp=semantic_by_fp,
        fp_id=fp_id,
        phase=phase,
        tension=tension,
        feasible_volume_proxy=feasible_volume,
        energy_sharpness=energy_sharpness,
        gate_verdict=gate_verdict,
    )

    anchor_id, anchor_dist, anchor_effective, density = find_nearest_ci_anchor(phase, telemetry=telemetry)

    prev_for_class = prev_runtime_phase
    if prev_for_class is None:
        ci_store = telemetry or ArbitrationTelemetryStore()
        latest_ci = ci_store.latest_ci_snapshot()
        if latest_ci and soft_comparable(latest_ci.identity, runtime_snap.identity):
            prev_for_class = latest_ci

    regime = classify_snapshot(runtime_snap, prev=prev_for_class)
    transition_label: str | None = None
    if prev_for_class:
        transition_label = classify_transition(prev_for_class, runtime_snap).transition_label

    structural = detect_structural_drift(anchor_effective, regime.invariant_class)
    gate_pass = bool(gate_verdict.pass_gate if gate_verdict else False)
    gate_admitted = bool(arbitration.gate_admitted)

    flags = list(regime.trigger_flags)
    if structural:
        flags.append("structural_runtime_deformation")

    frozen_gen = resolve_frozen_generation_identity(
        anchor_snapshot_id=anchor_id,
        runtime_identity=runtime_snap.identity,
        telemetry=telemetry,
    )

    soft = SoftSnapshot(
        snapshot_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
        fp_id=fp_id,
        patch_id=patch_id,
        s_final=round(top_s_final, 4),
        s_calibrated=round(top_s_calibrated, 4),
        s_arbitration=round(top_s_arbitration, 4),
        phase_norm=phase.normalized(),
        tension=tension,
        projection_iterations=0,
        gate_pass=gate_pass,
        gate_admitted=gate_admitted,
        nearest_ci_lattice_snapshot_id=anchor_id,
        soft_distance_to_anchor=anchor_dist,
        invariant_class=regime.invariant_class.value,
        manifold_generation_id=frozen_gen.manifold_generation_id,
        generation_source=frozen_gen.generation_source,
        generation_anchor_snapshot_id=frozen_gen.generation_anchor_snapshot_id,
        soft_distance_effective=anchor_effective,
        anchor_density=density,
        transition_label=transition_label,
        structural_drift_flag=structural,
        ci_fixture_review_suggested=False,
        trigger_flags=flags,
    )
    return soft, runtime_snap


@dataclass
class RuntimeSoftTelemetryStore:
    path: Path = field(default_factory=lambda: DEFAULT_RUNTIME_PATH)
    ci_telemetry_path: Path | None = None
    snapshots: list[SoftSnapshot] = field(default_factory=list)
    observer_events: list[ObserverEvent] = field(default_factory=list)
    _last_phase_by_fp: dict[str, PhaseSnapshot] = field(default_factory=dict)

    def _ci_telemetry(self) -> ArbitrationTelemetryStore:
        if self.ci_telemetry_path is not None:
            return ArbitrationTelemetryStore(self.ci_telemetry_path)
        return ArbitrationTelemetryStore()

    def __post_init__(self) -> None:
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        for row in raw.get("observer_events", []):
            self.observer_events.append(ObserverEvent(**row))
        for row in raw.get("snapshots", []):
            tension = TensionVector(**row["tension"])
            frozen_gen = backfill_soft_generation_identity(row, telemetry=self._ci_telemetry())
            self.snapshots.append(
                SoftSnapshot(
                    snapshot_id=row["snapshot_id"],
                    timestamp=row["timestamp"],
                    fp_id=row["fp_id"],
                    patch_id=row["patch_id"],
                    s_final=row["s_final"],
                    s_calibrated=row["s_calibrated"],
                    s_arbitration=row["s_arbitration"],
                    phase_norm=row["phase_norm"],
                    tension=tension,
                    projection_iterations=row.get("projection_iterations", 0),
                    gate_pass=row["gate_pass"],
                    gate_admitted=row["gate_admitted"],
                    nearest_ci_lattice_snapshot_id=row.get("nearest_ci_lattice_snapshot_id"),
                    soft_distance_to_anchor=row.get("soft_distance_to_anchor", 0.0),
                    invariant_class=row["invariant_class"],
                    manifold_generation_id=frozen_gen.manifold_generation_id,
                    generation_source=frozen_gen.generation_source,
                    generation_anchor_snapshot_id=frozen_gen.generation_anchor_snapshot_id,
                    soft_distance_effective=row.get("soft_distance_effective", 0.0),
                    anchor_density=row.get("anchor_density", 0.0),
                    transition_label=row.get("transition_label"),
                    structural_drift_flag=row.get("structural_drift_flag", False),
                    ci_fixture_review_suggested=row.get("ci_fixture_review_suggested", False),
                    trigger_flags=row.get("trigger_flags", []),
                )
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "telemetry_version": PHASE_SPACE_VERSION,
            "observer_version": OBSERVER_VERSION,
            "snapshots": [snapshot.to_dict() for snapshot in self.snapshots],
            "observer_events": [event.to_dict() for event in self.observer_events],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def record_observer_event(self, event: ObserverEvent, *, persist: bool = False) -> None:
        self.observer_events.append(event)
        if len(self.observer_events) > MAX_OBSERVER_EVENTS:
            self.observer_events = self.observer_events[-MAX_OBSERVER_EVENTS:]
        if persist:
            self.save()

    def observer_diagnostics(self, window: int = 50) -> ObserverDiagnostics:
        diag = compute_observer_independence(self.observer_events[-window:])
        densities = [snapshot.anchor_density for snapshot in self.snapshots[-window:] if snapshot.anchor_density]
        if densities:
            diag.anchor_density_mean = round(sum(densities) / len(densities), 4)
        return diag

    def latest_for_fp(self, fp_id: str) -> SoftSnapshot | None:
        for snapshot in reversed(self.snapshots):
            if snapshot.fp_id == fp_id:
                return snapshot
        return None

    def boundary_count_for_fp(self, fp_id: str, window: int = 10) -> int:
        recent = [s for s in self.snapshots if s.fp_id == fp_id][-window:]
        return sum(1 for s in recent if s.invariant_class == InvariantClass.I5_BOUNDARY_APPROACH.value)

    def append_if_compressed(
        self,
        candidate: SoftSnapshot,
        *,
        runtime_phase: PhaseSnapshot,
        persist: bool = True,
    ) -> SoftSnapshot | None:
        prev = self.latest_for_fp(candidate.fp_id)
        prev_regime = InvariantClass(prev.invariant_class) if prev else None
        store, reasons = should_store_snapshot(candidate, prev=prev, prev_regime=prev_regime)
        regime_changed = bool(prev_regime and InvariantClass(candidate.invariant_class) != prev_regime)

        self.record_observer_event(
            ObserverEvent(
                timestamp=candidate.timestamp,
                fp_id=candidate.fp_id,
                stored=store,
                invariant_class=candidate.invariant_class,
                regime_changed=regime_changed,
                compression_reasons=reasons if store else [],
            )
        )

        if candidate.invariant_class == InvariantClass.I5_BOUNDARY_APPROACH.value:
            if self.boundary_count_for_fp(candidate.fp_id) >= BOUNDARY_SUGGESTION_THRESHOLD:
                candidate.ci_fixture_review_suggested = True
                reasons.append("ci_fixture_review_suggested")

        if not store:
            return None

        candidate.trigger_flags = sorted(set(candidate.trigger_flags + reasons))
        self.snapshots.append(candidate)
        if len(self.snapshots) > MAX_RUNTIME_SNAPSHOTS:
            self.snapshots = self.snapshots[-MAX_RUNTIME_SNAPSHOTS:]
        self._last_phase_by_fp[candidate.fp_id] = runtime_phase
        if persist:
            self.save()
        return candidate

    def last_phase_for_fp(self, fp_id: str) -> PhaseSnapshot | None:
        return self._last_phase_by_fp.get(fp_id)


def emit_soft_snapshot_if_admitted(
    *,
    fp_id: str,
    patch_id: str,
    calibrated_list: list[CalibratedScore],
    cross_results: list[CrossClusterCalibrationResult],
    gate_verdict: GeometryGateVerdict | None,
    arbitration: BatchArbitrationVerdict,
    semantic_by_fp: dict[str, str],
    top_s_final: float,
    top_s_calibrated: float,
    top_s_arbitration: float,
    persist: bool = True,
    store: RuntimeSoftTelemetryStore | None = None,
    telemetry: ArbitrationTelemetryStore | None = None,
) -> SoftSnapshot | None:
    """Observer hook — emits compressed SOFT snapshot when gate admits arbitration."""
    if not gate_verdict or not arbitration.gate_admitted:
        return None

    runtime_store = store or RuntimeSoftTelemetryStore()
    prev_phase = runtime_store.last_phase_for_fp(fp_id)

    candidate, runtime_phase = build_soft_snapshot(
        fp_id=fp_id,
        patch_id=patch_id,
        calibrated_list=calibrated_list,
        cross_results=cross_results,
        gate_verdict=gate_verdict,
        arbitration=arbitration,
        semantic_by_fp=semantic_by_fp,
        top_s_final=top_s_final,
        top_s_calibrated=top_s_calibrated,
        top_s_arbitration=top_s_arbitration,
        prev_runtime_phase=prev_phase,
        telemetry=telemetry,
    )

    return runtime_store.append_if_compressed(
        candidate, runtime_phase=runtime_phase, persist=persist
    )


def format_runtime_observer_report(store: RuntimeSoftTelemetryStore | None = None) -> str:
    store = store or RuntimeSoftTelemetryStore()
    lines = [f"=== Runtime SOFT Observer | {OBSERVER_VERSION} ===", f"  snapshots={len(store.snapshots)}"]
    diag = store.observer_diagnostics()
    lines.append(
        f"  observer_independence={diag.observer_independence_score:.3f} "
        f"corr={diag.compression_regime_correlation:+.3f} "
        f"bias_warning={diag.bias_warning}"
    )
    if not store.snapshots:
        lines.append("  No runtime SOFT snapshots yet.")
        return "\n".join(lines)

    for snapshot in store.snapshots[-8:]:
        drift = " [DRIFT]" if snapshot.structural_drift_flag else ""
        review = " [CI_REVIEW?]" if snapshot.ci_fixture_review_suggested else ""
        lines.append(
            f"  {snapshot.timestamp[:19]} {snapshot.fp_id[:12]:12s} "
            f"{snapshot.invariant_class} gen={snapshot.manifold_generation_id[:12]} "
            f"d={snapshot.soft_distance_effective:.3f}"
            f"(raw={snapshot.soft_distance_to_anchor:.3f} rho={snapshot.anchor_density:.2f})"
            f"{drift}{review}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Runtime SOFT phase observer")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--diagnostics", action="store_true", help="Show observer independence diagnostics")
    args = parser.parse_args(argv)

    store = RuntimeSoftTelemetryStore()
    if args.diagnostics:
        diag = store.observer_diagnostics()
        if args.json:
            print(json.dumps(diag.to_dict(), indent=2))
        else:
            print(f"Observer independence score: {diag.observer_independence_score:.4f}")
            print(f"Compression/regime correlation: {diag.compression_regime_correlation:+.4f}")
            print(f"Bias warning: {diag.bias_warning} (threshold |corr| >= {TAU_BIAS})")
        return 1 if diag.bias_warning else 0

    if args.json:
        print(json.dumps([s.to_dict() for s in store.snapshots[-20:]], indent=2))
    else:
        print(format_runtime_observer_report(store))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
