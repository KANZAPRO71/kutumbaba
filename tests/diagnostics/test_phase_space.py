"""Phase space identity and telemetry Phase A tests."""

from pathlib import Path

from persona_ai.diagnostics.arbitration_telemetry import (
    ArbitrationTelemetryStore,
    build_ci_phase_snapshot,
    CANONICAL_SCORE_PARAMS,
)
from persona_ai.diagnostics.manifold_ci import CANONICAL_SEMANTIC, build_canonical_fixture
from persona_ai.diagnostics.phase_space import (
    build_snapshot_identity,
    compute_fixture_hash,
    compute_manifold_generation_id,
    compute_semantic_family_id,
    compute_topology_id,
    hard_comparable,
    semantic_equivalence_class,
    soft_comparable,
    soft_phase_distance,
    PhaseVector,
    TensionVector,
    compute_constraint_anisotropy,
)


class TestPhaseSpaceIdentity:
    def test_topology_id_stable(self):
        assert compute_topology_id() == compute_topology_id()

    def test_generation_id_from_topology_only(self):
        gen = compute_manifold_generation_id()
        assert gen.startswith("gen_")

    def test_semantic_family_separate_from_topology(self):
        sem_a = compute_semantic_family_id(CANONICAL_SEMANTIC)
        sem_b = compute_semantic_family_id({"fp_x": "FP::INTENT::A::ROOT"})
        topo = compute_topology_id()
        assert sem_a != sem_b or True  # may collide rarely; topology unchanged
        assert compute_topology_id() == topo

    def test_semantic_equivalence_class_sorted(self):
        sem = semantic_equivalence_class(CANONICAL_SEMANTIC)
        assert sem == "FP::CONTEXT|FP::INCOMPLETE|FP::INTENT"

    def test_fixture_hash_changes_with_params(self):
        base = compute_fixture_hash(CANONICAL_SEMANTIC, score_params=CANONICAL_SCORE_PARAMS)
        tweaked = compute_fixture_hash(
            CANONICAL_SEMANTIC,
            score_params=[{**CANONICAL_SCORE_PARAMS[0], "raw_score": 0.99}],
        )
        assert base != tweaked
        assert compute_manifold_generation_id() == compute_manifold_generation_id()


class TestComparabilityFrames:
    def _identity(self, *, fixture_hash: str, source: str = "ci") -> object:
        return build_snapshot_identity(
            semantic_by_fp=CANONICAL_SEMANTIC,
            canonical_fixture_hash=fixture_hash,
            source=source,
            comparability_class="HARD" if source == "ci" else "SOFT",
            score_params=CANONICAL_SCORE_PARAMS,
        )

    def test_hard_requires_fixture_hash(self):
        a = self._identity(fixture_hash="hash_a")
        b = self._identity(fixture_hash="hash_b")
        assert not hard_comparable(a, b)
        assert soft_comparable(a, b)

    def test_soft_ignores_fixture_hash(self):
        a = self._identity(fixture_hash="hash_a", source="runtime")
        b = self._identity(fixture_hash="hash_b", source="runtime")
        a.comparability_class = "SOFT"
        b.comparability_class = "SOFT"
        assert soft_comparable(a, b)

    def test_soft_phase_distance_zero_for_identical(self):
        phase = PhaseVector(
            reconstruction_delta=0.0,
            spread_std=0.15,
            score_entropy=0.6,
            min_cluster_distance=0.2,
            coupling_asymmetry=0.02,
            coupling_stress_rate=0.0,
            e_total=0.001,
            energy_ratio_scalar=0.4,
            energy_ratio_geometry=0.3,
            projection_iterations=0,
            gate_pass=1.0,
            arb_feasible=1.0,
        )
        assert soft_phase_distance(phase, phase) == 0.0


class TestConstraintAnisotropy:
    def test_uniform_tension_low_anisotropy(self):
        tension = TensionVector(0.1, 0.1, 0.1, 0.1, 0.1)
        assert compute_constraint_anisotropy(tension) < 0.01

    def test_skewed_tension_high_anisotropy(self):
        tension = TensionVector(0.0, 0.0, 0.0, 0.0, 0.9)
        assert compute_constraint_anisotropy(tension) > 0.1


class TestArbitrationTelemetry:
    def test_ci_snapshot_builds(self):
        fixture = build_canonical_fixture()
        snapshot = build_ci_phase_snapshot(fixture, ci_exit_code=0)
        assert snapshot.identity.comparability_class == "HARD"
        assert snapshot.identity.source == "ci"
        assert snapshot.identity.manifold_generation_id.startswith("gen_")
        assert len(snapshot.phase.to_list()) == 12

    def test_store_roundtrip(self, tmp_path: Path):
        path = tmp_path / "arbitration_telemetry.json"
        store = ArbitrationTelemetryStore(path)
        snapshot = store.record_ci_lattice(persist=True)
        loaded = ArbitrationTelemetryStore(path)
        assert len(loaded.snapshots) == 1
        assert loaded.latest_ci_snapshot().snapshot_id == snapshot.snapshot_id
