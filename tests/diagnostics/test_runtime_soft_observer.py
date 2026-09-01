"""Runtime SOFT observer Phase C tests."""

from pathlib import Path

from persona_ai.diagnostics.arbitration_telemetry import ArbitrationTelemetryStore, build_ci_phase_snapshot
from persona_ai.diagnostics.invariance_classifier import InvariantClass
from persona_ai.diagnostics.manifold_ci import build_canonical_fixture
from persona_ai.diagnostics.runtime_soft_observer import (
    RuntimeSoftTelemetryStore,
    build_soft_snapshot,
    detect_structural_drift,
    emit_soft_snapshot_if_admitted,
    find_nearest_ci_anchor,
    should_store_snapshot,
    SoftSnapshot,
)
from persona_ai.diagnostics.phase_space import TensionVector


def _arbitration_context():
    fixture = build_canonical_fixture()
    return (
        fixture,
        fixture.calibrated,
        fixture.cross_results,
        fixture.geometry_gate,
        fixture.arbitration,
    )


class TestRuntimeSoftObserver:
    def test_anchor_to_ci_lattice(self, tmp_path: Path):
        ci_path = tmp_path / "ci.json"
        ci_store = ArbitrationTelemetryStore(ci_path)
        fixture = build_canonical_fixture()
        ci_store.record_ci_lattice(fixture, persist=True)

        phase = build_ci_phase_snapshot(fixture).phase
        anchor_id, dist, effective, density = find_nearest_ci_anchor(phase, telemetry=ci_store)
        assert anchor_id is not None
        assert dist < 0.01
        assert effective <= dist
        assert density >= 0.0

    def test_build_soft_snapshot(self, tmp_path: Path):
        ci_store = ArbitrationTelemetryStore(tmp_path / "ci.json")
        fixture, calibrated, cross, gate, arbitration = _arbitration_context()
        ci_store.record_ci_lattice(fixture, persist=True)

        soft, _ = build_soft_snapshot(
            fp_id="fp_test",
            patch_id="p1",
            calibrated_list=calibrated,
            cross_results=cross,
            gate_verdict=gate,
            arbitration=arbitration,
            semantic_by_fp={"fp_test": "FP::INTENT::CTX::ROOT"},
            top_s_final=0.72,
            top_s_calibrated=0.75,
            top_s_arbitration=0.74,
            telemetry=ci_store,
        )
        assert soft.gate_admitted
        assert soft.nearest_ci_lattice_snapshot_id is not None
        assert soft.soft_distance_effective <= soft.soft_distance_to_anchor
        assert len(soft.phase_norm) == 12
        assert soft.generation_source == "ci_anchor"
        assert soft.manifold_generation_id
        assert soft.generation_anchor_snapshot_id == soft.nearest_ci_lattice_snapshot_id

    def test_frozen_generation_survives_reload(self, tmp_path: Path):
        ci_path = tmp_path / "ci.json"
        runtime_path = tmp_path / "runtime.json"
        ci_store = ArbitrationTelemetryStore(ci_path)
        fixture, calibrated, cross, gate, arbitration = _arbitration_context()
        ci_snap = ci_store.record_ci_lattice(fixture, persist=True)
        expected_gen = ci_snap.identity.manifold_generation_id

        runtime_store = RuntimeSoftTelemetryStore(runtime_path)
        emit_soft_snapshot_if_admitted(
            fp_id="fp_a",
            patch_id="p1",
            calibrated_list=calibrated,
            cross_results=cross,
            gate_verdict=gate,
            arbitration=arbitration,
            semantic_by_fp={"fp_a": "FP::INTENT::CTX::ROOT"},
            top_s_final=0.72,
            top_s_calibrated=0.75,
            top_s_arbitration=0.74,
            store=runtime_store,
            telemetry=ci_store,
        )
        frozen_gen = runtime_store.snapshots[0].manifold_generation_id

        reloaded = RuntimeSoftTelemetryStore(runtime_path)
        assert reloaded.snapshots[0].manifold_generation_id == frozen_gen
        assert reloaded.snapshots[0].manifold_generation_id == expected_gen
        assert reloaded.snapshots[0].generation_source == "ci_anchor"

    def test_legacy_backfill_from_ci_anchor_only(self, tmp_path: Path):
        ci_path = tmp_path / "ci.json"
        runtime_path = tmp_path / "runtime.json"
        ci_store = ArbitrationTelemetryStore(ci_path)
        ci_snap = ci_store.record_ci_lattice(build_canonical_fixture(), persist=True)

        legacy_payload = {
            "telemetry_version": "v1.1",
            "observer_version": "v1.1",
            "snapshots": [
                {
                    "snapshot_id": "legacy-1",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "fp_id": "fp_a",
                    "patch_id": "p1",
                    "s_final": 0.7,
                    "s_calibrated": 0.72,
                    "s_arbitration": 0.71,
                    "phase_norm": [0.0] * 12,
                    "tension": {
                        "scalar_residual": 0.01,
                        "geometry_residual": 0.01,
                        "separation_residual": 0.01,
                        "coupling_residual": 0.01,
                        "equilibrium_residual": 0.01,
                        "constraint_anisotropy": 0.01,
                    },
                    "gate_pass": True,
                    "gate_admitted": True,
                    "nearest_ci_lattice_snapshot_id": ci_snap.snapshot_id,
                    "soft_distance_to_anchor": 0.1,
                    "invariant_class": "I0",
                    "trigger_flags": ["regime_change"],
                }
            ],
            "observer_events": [],
        }
        runtime_path.write_text(__import__("json").dumps(legacy_payload), encoding="utf-8")

        store = RuntimeSoftTelemetryStore(runtime_path, ci_telemetry_path=ci_path)
        assert store.snapshots[0].manifold_generation_id == ci_snap.identity.manifold_generation_id
        assert store.snapshots[0].generation_source == "ci_anchor"
        assert store.snapshots[0].generation_anchor_snapshot_id == ci_snap.snapshot_id

    def test_effective_distance_reduces_with_density(self):
        from persona_ai.diagnostics.runtime_soft_observer import effective_soft_distance

        raw = 0.4
        low = effective_soft_distance(raw, 0.0)
        high = effective_soft_distance(raw, 1.0)
        assert low == raw
        assert high < raw

    def test_observer_independence_independent_events(self):
        from persona_ai.diagnostics.runtime_soft_observer import (
            ObserverEvent,
            compute_observer_independence,
        )

        events = [
            ObserverEvent("t", "fp", True, "I0", False, []),
            ObserverEvent("t", "fp", False, "I0", False, []),
            ObserverEvent("t", "fp", True, "I2", True, ["regime_change"]),
            ObserverEvent("t", "fp", False, "I2", False, []),
        ]
        diag = compute_observer_independence(events)
        assert diag.observer_independence_score >= 0.0
        assert diag.event_count == 4

    def test_observer_bias_warning_on_perfect_correlation(self):
        from persona_ai.diagnostics.runtime_soft_observer import (
            ObserverEvent,
            compute_observer_independence,
        )

        events = [
            ObserverEvent("t", "fp", stored, "I0", stored, [])
            for stored in (True, True, False, False)
        ]
        diag = compute_observer_independence(events)
        assert diag.bias_warning
        assert diag.compression_regime_correlation == 1.0

    def test_compression_first_observation(self):
        snap = SoftSnapshot(
            snapshot_id="a",
            timestamp="t",
            fp_id="fp",
            patch_id="p",
            s_final=0.7,
            s_calibrated=0.72,
            s_arbitration=0.71,
            phase_norm=[0.0] * 12,
            tension=TensionVector(0.01, 0.01, 0.01, 0.01, 0.01, 0.01),
            projection_iterations=0,
            gate_pass=True,
            gate_admitted=True,
            nearest_ci_lattice_snapshot_id="ci1",
            soft_distance_to_anchor=0.05,
            invariant_class=InvariantClass.I0_FIXED_POINT.value,
            manifold_generation_id="gen-frozen",
            generation_source="ci_anchor",
            generation_anchor_snapshot_id="ci1",
        )
        store, reasons = should_store_snapshot(snap, prev=None)
        assert store
        assert "first_observation" in reasons

    def test_structural_drift_detection(self):
        assert detect_structural_drift(0.5, InvariantClass.I4_TENSION_ACCUMULATION)
        assert not detect_structural_drift(0.1, InvariantClass.I4_TENSION_ACCUMULATION)

    def test_emit_if_admitted(self, tmp_path: Path):
        ci_store = ArbitrationTelemetryStore(tmp_path / "ci.json")
        runtime_store = RuntimeSoftTelemetryStore(tmp_path / "runtime.json")
        fixture, calibrated, cross, gate, arbitration = _arbitration_context()
        ci_store.record_ci_lattice(fixture, persist=True)

        result = emit_soft_snapshot_if_admitted(
            fp_id="fp_a",
            patch_id="p1",
            calibrated_list=calibrated,
            cross_results=cross,
            gate_verdict=gate,
            arbitration=arbitration,
            semantic_by_fp={"fp_a": "FP::INTENT::CTX::ROOT"},
            top_s_final=0.72,
            top_s_calibrated=0.75,
            top_s_arbitration=0.74,
            store=runtime_store,
            telemetry=ci_store,
        )
        assert result is not None
        assert len(runtime_store.snapshots) == 1
