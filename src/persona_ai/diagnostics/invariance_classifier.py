"""Invariance classifier v1 — manifold regime labeling (I0–I6).

Labels phase-space snapshots and transitions for deformation semantics.
Requires Phase A identity frames (HARD/SOFT) and arbitration telemetry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from persona_ai.diagnostics.phase_space import (
    PhaseSnapshot,
    PhaseVector,
    TensionVector,
    soft_comparable,
    soft_phase_distance,
)

CLASSIFIER_VERSION = "v1"

EPS_FIXED_POINT = 0.08
EPS_VOLUME = 0.02
EPS_TENSION = 0.05
EPS_ENERGY_RATIO = 0.15
ANISOTROPY_SPIKE = 0.08
BOUNDARY_PROJECTION_THRESHOLD = 2


class InvariantClass(str, Enum):
    I0_FIXED_POINT = "I0"
    I1_CONTRACTIVE = "I1"
    I2_EXPANSIVE = "I2"
    I3_ROTATIONAL = "I3"
    I4_TENSION_ACCUMULATION = "I4"
    I5_BOUNDARY_APPROACH = "I5"
    I6_GENESIS = "I6"

    @property
    def label(self) -> str:
        return _CLASS_LABELS[self]

    def to_dict(self) -> str:
        return self.value


_CLASS_LABELS = {
    InvariantClass.I0_FIXED_POINT: "fixed_point",
    InvariantClass.I1_CONTRACTIVE: "contractive",
    InvariantClass.I2_EXPANSIVE: "expansive",
    InvariantClass.I3_ROTATIONAL: "rotational",
    InvariantClass.I4_TENSION_ACCUMULATION: "tension_accumulation",
    InvariantClass.I5_BOUNDARY_APPROACH: "boundary_approach",
    InvariantClass.I6_GENESIS: "genesis",
}


@dataclass
class RegimeClassification:
    invariant_class: InvariantClass
    confidence: float
    trigger_flags: list[str] = field(default_factory=list)
    redistribution_instability: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "invariant_class": self.invariant_class.value,
            "label": self.invariant_class.label,
            "confidence": self.confidence,
            "trigger_flags": self.trigger_flags,
            "redistribution_instability": self.redistribution_instability,
        }


@dataclass
class TransitionClassification:
    from_class: InvariantClass
    to_class: InvariantClass
    transition_label: str
    confidence: float
    trigger_flags: list[str] = field(default_factory=list)
    delta_phase_distance: float = 0.0
    delta_volume: float = 0.0
    delta_tension_norm: float = 0.0
    redistribution_instability: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_class": self.from_class.value,
            "to_class": self.to_class.value,
            "transition_label": self.transition_label,
            "confidence": self.confidence,
            "trigger_flags": self.trigger_flags,
            "delta_phase_distance": self.delta_phase_distance,
            "delta_volume": self.delta_volume,
            "delta_tension_norm": self.delta_tension_norm,
            "redistribution_instability": self.redistribution_instability,
        }


def _energy_ratio_shift(prev: PhaseVector, curr: PhaseVector) -> float:
    return max(
        abs(curr.energy_ratio_scalar - prev.energy_ratio_scalar),
        abs(curr.energy_ratio_geometry - prev.energy_ratio_geometry),
    )


def _redistribution_instability(
    tension: TensionVector,
    invariant_class: InvariantClass,
    *,
    anisotropy_delta: float = 0.0,
) -> bool:
    if invariant_class not in (InvariantClass.I3_ROTATIONAL, InvariantClass.I4_TENSION_ACCUMULATION):
        return False
    return tension.constraint_anisotropy >= ANISOTROPY_SPIKE or anisotropy_delta >= ANISOTROPY_SPIKE


def classify_snapshot(
    snapshot: PhaseSnapshot,
    *,
    prev: PhaseSnapshot | None = None,
) -> RegimeClassification:
    """Classify a single snapshot — uses deltas when prev is SOFT-comparable."""
    flags: list[str] = []

    if prev and prev.identity.manifold_generation_id != snapshot.identity.manifold_generation_id:
        return RegimeClassification(
            invariant_class=InvariantClass.I6_GENESIS,
            confidence=1.0,
            trigger_flags=["generation_break"],
        )

    tension_norm = snapshot.tension.norm
    gate_fail = snapshot.phase.gate_pass < 1.0
    high_projection = snapshot.phase.projection_iterations >= BOUNDARY_PROJECTION_THRESHOLD

    if gate_fail or high_projection:
        flags.append("boundary_contact")
        return RegimeClassification(
            invariant_class=InvariantClass.I5_BOUNDARY_APPROACH,
            confidence=0.9 if gate_fail else 0.75,
            trigger_flags=flags,
        )

    if prev and soft_comparable(prev.identity, snapshot.identity):
        d_phase = soft_phase_distance(prev.phase, snapshot.phase)
        d_volume = snapshot.feasible_volume_proxy - prev.feasible_volume_proxy
        d_tension = tension_norm - prev.tension.norm
        ratio_shift = _energy_ratio_shift(prev.phase, snapshot.phase)

        if d_phase < EPS_FIXED_POINT and abs(d_volume) < EPS_VOLUME and abs(d_tension) < EPS_TENSION:
            return RegimeClassification(
                invariant_class=InvariantClass.I0_FIXED_POINT,
                confidence=0.95,
                trigger_flags=["phase_stable"],
            )

        if d_volume < -EPS_VOLUME and abs(d_tension) < EPS_TENSION:
            flags.append("volume_contracting")
            return RegimeClassification(
                invariant_class=InvariantClass.I1_CONTRACTIVE,
                confidence=0.85,
                trigger_flags=flags,
            )

        if d_volume > EPS_VOLUME and snapshot.phase.gate_pass >= 1.0:
            flags.append("volume_expanding")
            return RegimeClassification(
                invariant_class=InvariantClass.I2_EXPANSIVE,
                confidence=0.85,
                trigger_flags=flags,
            )

        if ratio_shift >= EPS_ENERGY_RATIO and abs(d_tension) < EPS_TENSION:
            flags.append("energy_ratio_rotation")
            aniso_delta = snapshot.tension.constraint_anisotropy - prev.tension.constraint_anisotropy
            redistribution = _redistribution_instability(
                snapshot.tension, InvariantClass.I3_ROTATIONAL, anisotropy_delta=aniso_delta
            )
            if redistribution:
                flags.append("redistribution_instability")
            return RegimeClassification(
                invariant_class=InvariantClass.I3_ROTATIONAL,
                confidence=0.8,
                trigger_flags=flags,
                redistribution_instability=redistribution,
            )

        if d_tension > EPS_TENSION and abs(d_volume) < EPS_VOLUME:
            flags.append("tension_rising")
            aniso_delta = snapshot.tension.constraint_anisotropy - prev.tension.constraint_anisotropy
            redistribution = _redistribution_instability(
                snapshot.tension, InvariantClass.I4_TENSION_ACCUMULATION, anisotropy_delta=aniso_delta
            )
            if redistribution:
                flags.append("redistribution_instability")
            return RegimeClassification(
                invariant_class=InvariantClass.I4_TENSION_ACCUMULATION,
                confidence=0.85,
                trigger_flags=flags,
                redistribution_instability=redistribution,
            )

    if tension_norm < EPS_TENSION and snapshot.feasible_volume_proxy > 0:
        return RegimeClassification(
            invariant_class=InvariantClass.I0_FIXED_POINT,
            confidence=0.7,
            trigger_flags=["low_tension_absolute"],
        )

    return RegimeClassification(
        invariant_class=InvariantClass.I2_EXPANSIVE,
        confidence=0.5,
        trigger_flags=["default_stable_expansion"],
    )


def classify_transition(
    prev: PhaseSnapshot,
    curr: PhaseSnapshot,
) -> TransitionClassification:
    """Label regime transition A → B with confidence and trigger flags."""
    from_class = classify_snapshot(prev).invariant_class
    to_class = classify_snapshot(curr, prev=prev).invariant_class

    if prev.identity.manifold_generation_id != curr.identity.manifold_generation_id:
        to_class = InvariantClass.I6_GENESIS

    d_phase = (
        soft_phase_distance(prev.phase, curr.phase)
        if soft_comparable(prev.identity, curr.identity)
        else float("inf")
    )
    d_volume = curr.feasible_volume_proxy - prev.feasible_volume_proxy
    d_tension = curr.tension.norm - prev.tension.norm
    aniso_delta = curr.tension.constraint_anisotropy - prev.tension.constraint_anisotropy

    flags: list[str] = []
    if to_class == InvariantClass.I5_BOUNDARY_APPROACH:
        flags.append("boundary_approach")
    if to_class == InvariantClass.I4_TENSION_ACCUMULATION and d_tension > EPS_TENSION:
        flags.append("tension_inflection")
    if to_class == InvariantClass.I3_ROTATIONAL:
        flags.append("constraint_dominance_shift")

    redistribution = _redistribution_instability(
        curr.tension, to_class, anisotropy_delta=aniso_delta
    )
    if redistribution:
        flags.append("redistribution_instability")

    confidence = 0.9 if from_class != to_class else 0.95
    if d_phase == float("inf"):
        confidence = 0.6

    return TransitionClassification(
        from_class=from_class,
        to_class=to_class,
        transition_label=f"{from_class.value} -> {to_class.value}",
        confidence=round(confidence, 3),
        trigger_flags=flags,
        delta_phase_distance=round(d_phase, 6) if d_phase != float("inf") else -1.0,
        delta_volume=round(d_volume, 6),
        delta_tension_norm=round(d_tension, 6),
        redistribution_instability=redistribution,
    )


@dataclass
class RegimeTimelineEntry:
    snapshot_id: str
    timestamp: str
    invariant_class: InvariantClass
    confidence: float
    trigger_flags: list[str]
    transition_from: str | None = None
    redistribution_instability: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "invariant_class": self.invariant_class.value,
            "label": self.invariant_class.label,
            "confidence": self.confidence,
            "trigger_flags": self.trigger_flags,
            "transition_from": self.transition_from,
            "redistribution_instability": self.redistribution_instability,
        }


def build_regime_timeline(snapshots: list[PhaseSnapshot]) -> list[RegimeTimelineEntry]:
    """Build manifold regime timeline from ordered snapshots."""
    if not snapshots:
        return []

    entries: list[RegimeTimelineEntry] = []
    prev: PhaseSnapshot | None = None
    for snapshot in snapshots:
        if prev:
            transition = classify_transition(prev, snapshot)
            regime = classify_snapshot(snapshot, prev=prev)
            entries.append(
                RegimeTimelineEntry(
                    snapshot_id=snapshot.snapshot_id,
                    timestamp=snapshot.timestamp,
                    invariant_class=regime.invariant_class,
                    confidence=regime.confidence,
                    trigger_flags=regime.trigger_flags + transition.trigger_flags,
                    transition_from=transition.transition_label,
                    redistribution_instability=regime.redistribution_instability
                    or transition.redistribution_instability,
                )
            )
        else:
            regime = classify_snapshot(snapshot)
            entries.append(
                RegimeTimelineEntry(
                    snapshot_id=snapshot.snapshot_id,
                    timestamp=snapshot.timestamp,
                    invariant_class=regime.invariant_class,
                    confidence=regime.confidence,
                    trigger_flags=regime.trigger_flags,
                    redistribution_instability=regime.redistribution_instability,
                )
            )
        prev = snapshot
    return entries


def format_manifold_regime_timeline(entries: list[RegimeTimelineEntry]) -> str:
    """ASCII manifold regime timeline panel."""
    lines = [
        f"=== Manifold Regime Timeline | {CLASSIFIER_VERSION} ===",
    ]
    if not entries:
        lines.append("  No phase-space snapshots — run manifold_ci --check --record-telemetry")
        return "\n".join(lines)

    regime_line = " ".join(entry.invariant_class.value for entry in entries)
    lines.append(f"  regime: {regime_line}")

    for index, entry in enumerate(entries):
        ts = entry.timestamp[:19] if entry.timestamp else "?"
        flag_str = f" flags={entry.trigger_flags}" if entry.trigger_flags else ""
        transition = f" ({entry.transition_from})" if entry.transition_from else ""
        instability = " [REDISTRIBUTION]" if entry.redistribution_instability else ""
        lines.append(
            f"  [{index + 1}] {ts} {entry.invariant_class.value}{transition} "
            f"conf={entry.confidence:.2f}{flag_str}{instability}"
        )

    inflections = [
        entry for entry in entries if "tension_inflection" in entry.trigger_flags
    ]
    if inflections:
        lines.append("")
        lines.append("  Inflection points:")
        for entry in inflections:
            lines.append(f"    {entry.timestamp[:19]} {entry.transition_from}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    from persona_ai.diagnostics.arbitration_telemetry import ArbitrationTelemetryStore

    parser = argparse.ArgumentParser(description="Manifold invariance classifier")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)

    store = ArbitrationTelemetryStore()
    ci_snapshots = [s for s in store.snapshots if s.identity.source == "ci"][-args.limit :]
    timeline = build_regime_timeline(ci_snapshots)

    if args.json:
        print(json.dumps([entry.to_dict() for entry in timeline], indent=2))
    else:
        print(format_manifold_regime_timeline(timeline))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
