"""Phase D — manifold dynamics Markov layer tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from persona_ai.diagnostics.arbitration_telemetry import ArbitrationTelemetryStore
from persona_ai.diagnostics.invariance_classifier import InvariantClass
from persona_ai.diagnostics.manifold_ci import build_canonical_fixture
from persona_ai.diagnostics.manifold_dynamics import (
    ALL_REGIMES,
    build_manifold_dynamics_report,
    build_transition_matrix,
    compute_drift_velocity_by_regime,
    compute_regime_half_life,
    extract_event_stream,
    validate_markov_consistency,
)
from persona_ai.diagnostics.phase_space import compute_manifold_generation_id
from persona_ai.diagnostics.runtime_soft_observer import RuntimeSoftTelemetryStore, SoftSnapshot
from persona_ai.diagnostics.phase_space import TensionVector


def _iso(offset_seconds: int = 0) -> str:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)
    return base.isoformat()


def _soft(
    *,
    snapshot_id: str,
    timestamp: str,
    invariant_class: str,
    d_effective: float = 0.1,
    structural_drift: bool = False,
    trigger_flags: list[str] | None = None,
    generation_id: str = "gen-test",
) -> SoftSnapshot:
    return SoftSnapshot(
        snapshot_id=snapshot_id,
        timestamp=timestamp,
        fp_id="fp_a",
        patch_id="p1",
        s_final=0.7,
        s_calibrated=0.72,
        s_arbitration=0.71,
        phase_norm=[0.0] * 12,
        tension=TensionVector(0.01, 0.01, 0.01, 0.01, 0.01, 0.01),
        projection_iterations=0,
        gate_pass=True,
        gate_admitted=True,
        nearest_ci_lattice_snapshot_id="ci-1",
        soft_distance_to_anchor=0.2,
        invariant_class=invariant_class,
        manifold_generation_id=generation_id,
        generation_source="ci_anchor",
        generation_anchor_snapshot_id="ci-1",
        soft_distance_effective=d_effective,
        anchor_density=0.5,
        structural_drift_flag=structural_drift,
        trigger_flags=trigger_flags or ["regime_change"],
    )


class TestManifoldDynamics:
    def test_event_stream_filters_compression(self, tmp_path: Path):
        ci_store = ArbitrationTelemetryStore(tmp_path / "ci.json")
        fixture = build_canonical_fixture()
        ci_store.record_ci_lattice(fixture, persist=True)

        runtime_store = RuntimeSoftTelemetryStore(tmp_path / "runtime.json")
        runtime_store.snapshots = [
            _soft(snapshot_id="s1", timestamp=_iso(10), invariant_class="I0", trigger_flags=["regime_change"]),
            SoftSnapshot(
                snapshot_id="s2",
                timestamp=_iso(20),
                fp_id="fp_a",
                patch_id="p1",
                s_final=0.7,
                s_calibrated=0.72,
                s_arbitration=0.71,
                phase_norm=[0.0] * 12,
                tension=TensionVector(0.01, 0.01, 0.01, 0.01, 0.01, 0.01),
                projection_iterations=0,
                gate_pass=True,
                gate_admitted=True,
                nearest_ci_lattice_snapshot_id="ci-1",
                soft_distance_to_anchor=0.2,
                invariant_class="I1",
                manifold_generation_id="gen-test",
                generation_source="ci_anchor",
                generation_anchor_snapshot_id="ci-1",
                soft_distance_effective=0.15,
                trigger_flags=[],
            ),
            _soft(
                snapshot_id="s3",
                timestamp=_iso(30),
                invariant_class="I4",
                structural_drift=True,
                trigger_flags=["structural_deformation"],
            ),
        ]

        events = extract_event_stream(ci_store=ci_store, runtime_store=runtime_store)
        assert len(events) == 3
        kinds = {event.event_kind for event in events}
        assert kinds == {"ci_lattice", "regime_change", "structural_drift"}
        assert sum(1 for event in events if event.lossy) == 2
        assert sum(1 for event in events if not event.lossy) == 1

    def test_transition_matrix_laplace_and_energy(self, tmp_path: Path):
        from persona_ai.diagnostics.manifold_dynamics import ManifoldEvent

        gen = compute_manifold_generation_id()
        events = [
            ManifoldEvent(
                timestamp=_iso(100),
                invariant_class="I0",
                generation_id=gen,
                d_effective=0.1,
                anchor_density=0.0,
                source="runtime",
                event_kind="regime_change",
                snapshot_id="e1",
            ),
            ManifoldEvent(
                timestamp=_iso(110),
                invariant_class="I1",
                generation_id=gen,
                d_effective=0.2,
                anchor_density=0.0,
                source="runtime",
                event_kind="regime_change",
                snapshot_id="e2",
            ),
            ManifoldEvent(
                timestamp=_iso(120),
                invariant_class="I0",
                generation_id=gen,
                d_effective=0.3,
                anchor_density=0.0,
                source="runtime",
                event_kind="regime_change",
                snapshot_id="e3",
            ),
        ]

        matrix = build_transition_matrix(events, generation_id=gen)
        assert matrix is not None
        assert matrix.sample_transitions >= 2
        for regime in ALL_REGIMES:
            row_sum = sum(matrix.probabilities[regime].values())
            assert abs(row_sum - 1.0) < 1e-5
            for target in ALL_REGIMES:
                probability = matrix.probabilities[regime][target]
                energy = matrix.energy[regime][target]
                assert energy == round(-__import__("math").log(max(probability, 1e-12)), 6)

    def test_drift_velocity_per_regime(self):
        from persona_ai.diagnostics.manifold_dynamics import ManifoldEvent

        gen = compute_manifold_generation_id()
        events = [
            ManifoldEvent(
                timestamp=_iso(0),
                invariant_class="I0",
                generation_id=gen,
                d_effective=0.0,
                anchor_density=0.0,
                source="runtime",
                event_kind="regime_change",
                snapshot_id="a",
            ),
            ManifoldEvent(
                timestamp=_iso(10),
                invariant_class="I0",
                generation_id=gen,
                d_effective=0.5,
                anchor_density=0.0,
                source="runtime",
                event_kind="regime_change",
                snapshot_id="b",
            ),
            ManifoldEvent(
                timestamp=_iso(20),
                invariant_class="I1",
                generation_id=gen,
                d_effective=0.7,
                anchor_density=0.0,
                source="runtime",
                event_kind="regime_change",
                snapshot_id="c",
            ),
        ]
        drift = compute_drift_velocity_by_regime(events)
        assert drift.mean_by_regime["I0"] == 0.035
        assert drift.mean_by_regime["I1"] == 0.0

    def test_regime_half_life(self):
        from persona_ai.diagnostics.manifold_dynamics import ManifoldEvent

        gen = compute_manifold_generation_id()
        events = [
            ManifoldEvent(
                timestamp=_iso(0),
                invariant_class="I0",
                generation_id=gen,
                d_effective=0.0,
                anchor_density=0.0,
                source="runtime",
                event_kind="regime_change",
                snapshot_id="a",
            ),
            ManifoldEvent(
                timestamp=_iso(10),
                invariant_class="I0",
                generation_id=gen,
                d_effective=0.1,
                anchor_density=0.0,
                source="runtime",
                event_kind="regime_change",
                snapshot_id="b",
            ),
            ManifoldEvent(
                timestamp=_iso(30),
                invariant_class="I1",
                generation_id=gen,
                d_effective=0.2,
                anchor_density=0.0,
                source="runtime",
                event_kind="regime_change",
                snapshot_id="c",
            ),
        ]
        half_life = compute_regime_half_life(events)
        assert half_life.half_life_events["I0"] == 2.0
        assert half_life.half_life_seconds["I0"] == 30.0

    def test_markov_validation_insufficient_samples(self):
        from persona_ai.diagnostics.manifold_dynamics import ManifoldEvent

        gen = compute_manifold_generation_id()
        events = [
            ManifoldEvent(
                timestamp=_iso(0),
                invariant_class=InvariantClass.I0_FIXED_POINT.value,
                generation_id=gen,
                d_effective=0.0,
                anchor_density=0.0,
                source="runtime",
                event_kind="regime_change",
                snapshot_id="a",
            )
        ]
        report = validate_markov_consistency(events, build_transition_matrix(events))
        assert report.valid is False
        assert report.sufficient_samples is False

    def test_build_report_integration(self, tmp_path: Path):
        ci_store = ArbitrationTelemetryStore(tmp_path / "ci.json")
        ci_store.record_ci_lattice(build_canonical_fixture(), persist=True)
        runtime_store = RuntimeSoftTelemetryStore(tmp_path / "runtime.json")
        runtime_store.snapshots = [
            _soft(snapshot_id="s1", timestamp=_iso(10), invariant_class="I0"),
            _soft(snapshot_id="s2", timestamp=_iso(20), invariant_class="I2"),
        ]
        report = build_manifold_dynamics_report(ci_store=ci_store, runtime_store=runtime_store)
        assert report.event_count >= 3
        assert report.version == "v1.1"
