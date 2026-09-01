"""Tests for invariance classifier I0–I6."""

from persona_ai.diagnostics.invariance_classifier import (
    InvariantClass,
    build_regime_timeline,
    classify_snapshot,
    classify_transition,
    format_manifold_regime_timeline,
)
from persona_ai.diagnostics.manifold_ci import build_canonical_fixture
from persona_ai.diagnostics.arbitration_telemetry import build_ci_phase_snapshot
from persona_ai.diagnostics.phase_space import (
    PhaseSnapshot,
    PhaseSnapshotIdentity,
    PhaseVector,
    TensionVector,
    build_snapshot_identity,
)
from persona_ai.diagnostics.manifold_ci import CANONICAL_SEMANTIC
from persona_ai.diagnostics.arbitration_telemetry import CANONICAL_SCORE_PARAMS, _canonical_fixture_hash


def _snapshot(
    *,
    volume: float = 0.05,
    tension_norm: float = 0.05,
    gate_pass: float = 1.0,
    projection_iters: int = 0,
    anisotropy: float = 0.01,
    generation_id: str = "gen_test",
    fixture_hash: str = "fixture_a",
) -> PhaseSnapshot:
    identity = PhaseSnapshotIdentity(
        topology_id="topo_a",
        semantic_family_id="sem_a",
        manifold_generation_id=generation_id,
        semantic_equivalence_class="FP::INTENT|FP::B",
        canonical_fixture_hash=fixture_hash,
        scoring_surface_version="S_final_v1",
        geometry_gate_version="v1",
        arbitration_version="v1.3",
        source="ci",
        comparability_class="HARD",
    )
    tension = TensionVector(0.05, 0.05, 0.05, 0.05, 0.05, anisotropy)
    return PhaseSnapshot(
        snapshot_id="snap",
        timestamp="2026-01-01T00:00:00Z",
        identity=identity,
        phase=PhaseVector(
            reconstruction_delta=0.0,
            spread_std=0.15,
            score_entropy=0.6,
            min_cluster_distance=0.2,
            coupling_asymmetry=0.02,
            coupling_stress_rate=0.0,
            e_total=0.001,
            energy_ratio_scalar=0.4,
            energy_ratio_geometry=0.3,
            projection_iterations=projection_iters,
            gate_pass=gate_pass,
            arb_feasible=1.0,
        ),
        tension=tension,
        feasible_volume_proxy=volume,
        energy_sharpness=0.001,
        ci_exit_code=0,
    )


class TestInvarianceClassifier:
    def test_i0_fixed_point(self):
        prev = _snapshot(volume=0.05, tension_norm=0.05)
        curr = _snapshot(volume=0.051, tension_norm=0.05)
        regime = classify_snapshot(curr, prev=prev)
        assert regime.invariant_class == InvariantClass.I0_FIXED_POINT

    def test_i1_contractive(self):
        prev = _snapshot(volume=0.08)
        curr = _snapshot(volume=0.04)
        regime = classify_snapshot(curr, prev=prev)
        assert regime.invariant_class == InvariantClass.I1_CONTRACTIVE

    def test_i2_expansive(self):
        prev = _snapshot(volume=0.04)
        curr = _snapshot(volume=0.09)
        regime = classify_snapshot(curr, prev=prev)
        assert regime.invariant_class == InvariantClass.I2_EXPANSIVE

    def test_i5_boundary_approach(self):
        snap = _snapshot(gate_pass=0.0, projection_iters=3)
        regime = classify_snapshot(snap)
        assert regime.invariant_class == InvariantClass.I5_BOUNDARY_APPROACH

    def test_i6_genesis(self):
        prev = _snapshot(generation_id="gen_old")
        curr = _snapshot(generation_id="gen_new")
        transition = classify_transition(prev, curr)
        assert transition.to_class == InvariantClass.I6_GENESIS

    def test_redistribution_instability(self):
        prev = _snapshot(anisotropy=0.01)
        curr = _snapshot(anisotropy=0.12)
        curr.phase.energy_ratio_scalar = 0.7
        prev.phase.energy_ratio_scalar = 0.3
        regime = classify_snapshot(curr, prev=prev)
        assert regime.invariant_class in (
            InvariantClass.I3_ROTATIONAL,
            InvariantClass.I4_TENSION_ACCUMULATION,
        )

    def test_ci_snapshot_classifies(self):
        fixture = build_canonical_fixture()
        snap = build_ci_phase_snapshot(fixture)
        regime = classify_snapshot(snap)
        assert regime.invariant_class in InvariantClass

    def test_regime_timeline(self):
        fixture = build_canonical_fixture()
        s1 = build_ci_phase_snapshot(fixture)
        s2 = build_ci_phase_snapshot(fixture)
        timeline = build_regime_timeline([s1, s2])
        assert len(timeline) == 2
        text = format_manifold_regime_timeline(timeline)
        assert "Manifold Regime Timeline" in text
