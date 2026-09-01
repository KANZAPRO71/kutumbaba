"""Manifold Dynamics Phase D — Markov partition of constrained dynamical manifold.

Treats telemetry as a lossy observation operator. Builds dynamics on a filtered
event stream (not raw uniform timeline):

  - CI lattice points (authoritative)
  - regime_change events
  - structural_drift events

Includes Phase D.1 Markov consistency validation (entropy + stationarity).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from collections import Counter

from persona_ai.diagnostics.arbitration_telemetry import ArbitrationTelemetryStore
from persona_ai.diagnostics.invariance_classifier import InvariantClass, classify_snapshot
from persona_ai.diagnostics.phase_space import PhaseSnapshot
from persona_ai.diagnostics.runtime_soft_observer import RuntimeSoftTelemetryStore

DYNAMICS_VERSION = "v1.1"
LAPLACE_ALPHA = 1.0
MIN_EVENTS_FOR_MATRIX = 3
MIN_DELTA_SECONDS = 1.0
STATIONARITY_TOLERANCE = 0.25

EventKind = Literal["ci_lattice", "regime_change", "structural_drift"]


class InvariantClassCode(str, Enum):
    """String codes matching InvariantClass values."""

    I0 = "I0"
    I1 = "I1"
    I2 = "I2"
    I3 = "I3"
    I4 = "I4"
    I5 = "I5"
    I6 = "I6"


ALL_REGIMES = [c.value for c in InvariantClass]


@dataclass
class ManifoldEvent:
    timestamp: str
    invariant_class: str
    generation_id: str
    d_effective: float
    anchor_density: float
    source: str
    event_kind: EventKind
    snapshot_id: str
    lossy: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def dt_seconds(self) -> float | None:
        return None


def _parse_ts(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _seconds_between(a: str, b: str) -> float:
    return max(MIN_DELTA_SECONDS, (_parse_ts(b) - _parse_ts(a)).total_seconds())


def _classify_ci_snapshot(
    snapshot: PhaseSnapshot,
    prev: PhaseSnapshot | None,
) -> str:
    regime = classify_snapshot(snapshot, prev=prev)
    return regime.invariant_class.value


def _primary_generation_id(events: list[ManifoldEvent]) -> str | None:
    """Dominant frozen generation frame in the event stream."""
    ids = [event.generation_id for event in events if event.generation_id]
    if not ids:
        return None
    return Counter(ids).most_common(1)[0][0]


def extract_event_stream(
    *,
    ci_store: ArbitrationTelemetryStore | None = None,
    runtime_store: RuntimeSoftTelemetryStore | None = None,
) -> list[ManifoldEvent]:
    """Canonical filtered event stream E(t) for Markov analysis."""
    ci_store = ci_store or ArbitrationTelemetryStore()
    runtime_store = runtime_store or RuntimeSoftTelemetryStore()
    events: list[ManifoldEvent] = []

    prev_ci: PhaseSnapshot | None = None
    for snapshot in ci_store.snapshots:
        if snapshot.identity.source != "ci":
            continue
        if snapshot.identity.comparability_class not in ("HARD", "GENESIS"):
            continue
        regime = _classify_ci_snapshot(snapshot, prev_ci)
        events.append(
            ManifoldEvent(
                timestamp=snapshot.timestamp,
                invariant_class=regime,
                generation_id=snapshot.identity.manifold_generation_id,
                d_effective=0.0,
                anchor_density=0.0,
                source="ci",
                event_kind="ci_lattice",
                snapshot_id=snapshot.snapshot_id,
                lossy=False,
            )
        )
        prev_ci = snapshot

    for soft in runtime_store.snapshots:
        kind: EventKind | None = None
        if soft.structural_drift_flag:
            kind = "structural_drift"
        elif "regime_change" in soft.trigger_flags:
            kind = "regime_change"
        elif "first_observation" in soft.trigger_flags:
            kind = "regime_change"
        if kind is None:
            continue
        if not soft.manifold_generation_id:
            continue
        events.append(
            ManifoldEvent(
                timestamp=soft.timestamp,
                invariant_class=soft.invariant_class,
                generation_id=soft.manifold_generation_id,
                d_effective=soft.soft_distance_effective,
                anchor_density=soft.anchor_density,
                source="runtime",
                event_kind=kind,
                snapshot_id=soft.snapshot_id,
                lossy=True,
            )
        )

    events.sort(key=lambda event: event.timestamp)
    return events


@dataclass
class TransitionMatrix:
    generation_id: str
    counts: dict[str, dict[str, float]]
    probabilities: dict[str, dict[str, float]]
    energy: dict[str, dict[str, float]]
    sample_transitions: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation_id": self.generation_id,
            "counts": self.counts,
            "probabilities": self.probabilities,
            "energy": self.energy,
            "sample_transitions": self.sample_transitions,
        }


def build_transition_matrix(
    events: list[ManifoldEvent],
    *,
    generation_id: str | None = None,
    alpha: float = LAPLACE_ALPHA,
) -> TransitionMatrix | None:
    """P(I_j | I_i) with Laplace smoothing, conditioned on frozen generation_id."""
    gen = generation_id or _primary_generation_id(events)
    if not gen:
        return None
    filtered = [event for event in events if event.generation_id == gen]
    if len(filtered) < MIN_EVENTS_FOR_MATRIX:
        return None

    counts: dict[str, dict[str, float]] = {
        regime: {target: alpha for target in ALL_REGIMES} for regime in ALL_REGIMES
    }
    transitions = 0
    for prev, curr in zip(filtered, filtered[1:]):
        if prev.generation_id != curr.generation_id:
            continue
        if prev.invariant_class not in counts or curr.invariant_class not in counts[prev.invariant_class]:
            continue
        counts[prev.invariant_class][curr.invariant_class] += 1.0
        transitions += 1

    probabilities: dict[str, dict[str, float]] = {}
    energy: dict[str, dict[str, float]] = {}
    for source_regime, row in counts.items():
        total = sum(row.values())
        probabilities[source_regime] = {
            target: round(row[target] / total, 6) for target in ALL_REGIMES
        }
        energy[source_regime] = {
            target: round(-math.log(max(probabilities[source_regime][target], 1e-12)), 6)
            for target in ALL_REGIMES
        }

    return TransitionMatrix(
        generation_id=gen,
        counts=counts,
        probabilities=probabilities,
        energy=energy,
        sample_transitions=transitions,
    )


@dataclass
class DriftVelocityReport:
    velocities_by_regime: dict[str, list[float]]
    mean_by_regime: dict[str, float]
    sample_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "velocities_by_regime": self.velocities_by_regime,
            "mean_by_regime": self.mean_by_regime,
            "sample_count": self.sample_count,
        }


def compute_drift_velocity_by_regime(events: list[ManifoldEvent]) -> DriftVelocityReport:
    """v_effective = |Δ d_effective| / Δt attributed to source regime."""
    velocities: dict[str, list[float]] = {regime: [] for regime in ALL_REGIMES}
    for prev, curr in zip(events, events[1:]):
        dt = _seconds_between(prev.timestamp, curr.timestamp)
        delta_d = abs(curr.d_effective - prev.d_effective)
        if prev.invariant_class in velocities:
            velocities[prev.invariant_class].append(round(delta_d / dt, 6))

    means = {
        regime: round(sum(values) / len(values), 6) if values else 0.0
        for regime, values in velocities.items()
    }
    return DriftVelocityReport(
        velocities_by_regime=velocities,
        mean_by_regime=means,
        sample_count=sum(len(values) for values in velocities.values()),
    )


@dataclass
class RegimeHalfLifeReport:
    half_life_seconds: dict[str, float]
    half_life_events: dict[str, float]
    segment_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def compute_regime_half_life(events: list[ManifoldEvent]) -> RegimeHalfLifeReport:
    """Median persistence duration per regime on filtered event stream."""
    if not events:
        return RegimeHalfLifeReport(half_life_seconds={}, half_life_events={}, segment_count=0)

    durations_seconds: dict[str, list[float]] = {regime: [] for regime in ALL_REGIMES}
    durations_events: dict[str, list[float]] = {regime: [] for regime in ALL_REGIMES}

    segment_start = 0
    for index in range(1, len(events)):
        if events[index].invariant_class != events[segment_start].invariant_class:
            regime = events[segment_start].invariant_class
            if regime in durations_seconds:
                durations_seconds[regime].append(
                    _seconds_between(events[segment_start].timestamp, events[index].timestamp)
                )
                durations_events[regime].append(float(index - segment_start))
            segment_start = index

    regime = events[segment_start].invariant_class
    if segment_start < len(events) - 1 and regime in durations_seconds:
        durations_seconds[regime].append(
            _seconds_between(events[segment_start].timestamp, events[-1].timestamp)
        )
        durations_events[regime].append(float(len(events) - segment_start))

    return RegimeHalfLifeReport(
        half_life_seconds={
            regime: round(_median(durations_seconds[regime]), 4)
            for regime in ALL_REGIMES
            if durations_seconds[regime]
        },
        half_life_events={
            regime: round(_median(durations_events[regime]), 4)
            for regime in ALL_REGIMES
            if durations_events[regime]
        },
        segment_count=sum(1 for values in durations_events.values() for _ in values),
    )


@dataclass
class MarkovConsistencyReport:
    valid: bool
    row_entropy_mean: float
    row_entropy_std: float
    stationarity_delta: float
    sufficient_samples: bool
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _row_entropy(matrix: dict[str, dict[str, float]]) -> list[float]:
    entropies: list[float] = []
    for row in matrix.values():
        values = [probability for probability in row.values() if probability > 0]
        if not values:
            continue
        entropies.append(-sum(p * math.log(p) for p in values))
    return entropies


def validate_markov_consistency(
    events: list[ManifoldEvent],
    matrix: TransitionMatrix | None,
) -> MarkovConsistencyReport:
    """Phase D.1 — entropy stability + split-half stationarity."""
    warnings: list[str] = []
    if matrix is None or matrix.sample_transitions < MIN_EVENTS_FOR_MATRIX:
        return MarkovConsistencyReport(
            valid=False,
            row_entropy_mean=0.0,
            row_entropy_std=0.0,
            stationarity_delta=1.0,
            sufficient_samples=False,
            warnings=["insufficient transitions for Markov validation"],
        )

    entropies = _row_entropy(matrix.probabilities)
    mean_h = sum(entropies) / len(entropies) if entropies else 0.0
    std_h = (
        math.sqrt(sum((value - mean_h) ** 2 for value in entropies) / len(entropies))
        if entropies
        else 0.0
    )

    if mean_h < 0.1:
        warnings.append("degenerate_transition_matrix_low_entropy")
    if mean_h > math.log(len(ALL_REGIMES)) - 0.05:
        warnings.append("near_uniform_transition_matrix")

    mid = len(events) // 2
    first_half = build_transition_matrix(events[: max(mid, MIN_EVENTS_FOR_MATRIX)])
    second_half = build_transition_matrix(events[mid:])
    stationarity_delta = 0.0
    if first_half and second_half:
        for regime in ALL_REGIMES:
            for target in ALL_REGIMES:
                stationarity_delta = max(
                    stationarity_delta,
                    abs(
                        first_half.probabilities.get(regime, {}).get(target, 0.0)
                        - second_half.probabilities.get(regime, {}).get(target, 0.0)
                    ),
                )
    if stationarity_delta > STATIONARITY_TOLERANCE:
        warnings.append(f"non_stationary_split_delta={stationarity_delta:.3f}")

    valid = not warnings or stationarity_delta <= STATIONARITY_TOLERANCE
    return MarkovConsistencyReport(
        valid=valid,
        row_entropy_mean=round(mean_h, 4),
        row_entropy_std=round(std_h, 4),
        stationarity_delta=round(stationarity_delta, 4),
        sufficient_samples=True,
        warnings=warnings,
    )


@dataclass
class ManifoldDynamicsReport:
    version: str
    event_count: int
    lossy_event_count: int
    events: list[ManifoldEvent]
    transition_matrix: TransitionMatrix | None
    drift_velocity: DriftVelocityReport
    half_life: RegimeHalfLifeReport
    markov_consistency: MarkovConsistencyReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "dynamics_version": self.version,
            "event_count": self.event_count,
            "lossy_event_count": self.lossy_event_count,
            "events": [event.to_dict() for event in self.events],
            "transition_matrix": self.transition_matrix.to_dict() if self.transition_matrix else None,
            "drift_velocity": self.drift_velocity.to_dict(),
            "half_life": self.half_life.to_dict(),
            "markov_consistency": self.markov_consistency.to_dict(),
        }


def build_manifold_dynamics_report(
    *,
    ci_store: ArbitrationTelemetryStore | None = None,
    runtime_store: RuntimeSoftTelemetryStore | None = None,
) -> ManifoldDynamicsReport:
    events = extract_event_stream(ci_store=ci_store, runtime_store=runtime_store)
    matrix = build_transition_matrix(events)
    drift = compute_drift_velocity_by_regime(events)
    half_life = compute_regime_half_life(events)
    consistency = validate_markov_consistency(events, matrix)
    return ManifoldDynamicsReport(
        version=DYNAMICS_VERSION,
        event_count=len(events),
        lossy_event_count=sum(1 for event in events if event.lossy),
        events=events,
        transition_matrix=matrix,
        drift_velocity=drift,
        half_life=half_life,
        markov_consistency=consistency,
    )


def format_manifold_dynamics_report(report: ManifoldDynamicsReport) -> str:
    lines = [
        f"=== Manifold Dynamics | Phase D {report.version} ===",
        f"  events={report.event_count} (lossy={report.lossy_event_count})",
        f"  markov_valid={report.markov_consistency.valid} "
        f"H_row={report.markov_consistency.row_entropy_mean:.3f} "
        f"stationarity_delta={report.markov_consistency.stationarity_delta:.3f}",
    ]
    if report.markov_consistency.warnings:
        lines.append(f"  warnings: {', '.join(report.markov_consistency.warnings)}")

    if report.transition_matrix:
        lines.append("")
        lines.append(f"  Transition matrix (gen={report.transition_matrix.generation_id[:16]}...):")
        for regime in ALL_REGIMES:
            row = report.transition_matrix.probabilities.get(regime, {})
            top = sorted(row.items(), key=lambda item: -item[1])[:3]
            if any(probability > 0.01 for _, probability in top):
                formatted = " ".join(f"{target}:{probability:.2f}" for target, probability in top if probability > 0.01)
                lines.append(f"    {regime} -> {formatted}")

    if report.half_life.half_life_events:
        lines.append("")
        lines.append("  Regime half-life (events):")
        for regime, value in sorted(report.half_life.half_life_events.items()):
            lines.append(f"    {regime}: {value:.1f}")

    if report.drift_velocity.mean_by_regime:
        lines.append("")
        lines.append("  Drift velocity v_effective (mean |Δd|/Δt):")
        for regime, value in sorted(report.drift_velocity.mean_by_regime.items()):
            if value > 0:
                lines.append(f"    {regime}: {value:.6f}")

    if report.events:
        lines.append("")
        regime_line = " ".join(event.invariant_class for event in report.events[-12:])
        lines.append(f"  event regime: {regime_line}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Manifold dynamics — Markov partition analysis")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = build_manifold_dynamics_report()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_manifold_dynamics_report(report))
    return 0 if report.markov_consistency.valid or report.event_count < MIN_EVENTS_FOR_MATRIX else 1


if __name__ == "__main__":
    raise SystemExit(main())
