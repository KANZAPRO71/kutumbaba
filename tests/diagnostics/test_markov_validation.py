"""Phase D.1 — Markov validation layer tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from persona_ai.diagnostics.arbitration_telemetry import ArbitrationTelemetryStore
from persona_ai.diagnostics.manifold_ci import build_canonical_fixture
from persona_ai.diagnostics.manifold_dynamics import ManifoldEvent, build_transition_matrix
from persona_ai.diagnostics.markov_validation import (
    MarkovBaselineStore,
    build_markov_validation_report,
    compute_kl_divergence_rate,
    split_events_by_ci_commit,
    evaluate_markov_order,
    evaluate_kernel_stationarity,
)
from persona_ai.diagnostics.phase_space import compute_manifold_generation_id


def _iso(offset_seconds: int = 0) -> str:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)
    return base.isoformat()


def _event(
    *,
    offset: int,
    regime: str,
    generation_id: str,
    kind: str = "regime_change",
    snapshot_id: str | None = None,
    lossy: bool = True,
) -> ManifoldEvent:
    return ManifoldEvent(
        timestamp=_iso(offset),
        invariant_class=regime,
        generation_id=generation_id,
        d_effective=0.1,
        anchor_density=0.0,
        source="runtime" if kind != "ci_lattice" else "ci",
        event_kind=kind,  # type: ignore[arg-type]
        snapshot_id=snapshot_id or f"s-{offset}",
        lossy=lossy,
    )


class TestMarkovValidation:
    def test_markov_order_first_order_sufficient(self):
        gen = "gen-fixed"
        events = [
            _event(offset=0, regime="I0", generation_id=gen),
            _event(offset=10, regime="I1", generation_id=gen),
            _event(offset=20, regime="I0", generation_id=gen),
            _event(offset=30, regime="I1", generation_id=gen),
            _event(offset=40, regime="I0", generation_id=gen),
        ]
        report = evaluate_markov_order(events, generation_id=gen)
        assert report.sufficient_samples
        assert report.order1_valid
        assert not report.hidden_memory_detected

    def test_markov_order_detects_hidden_memory(self):
        gen = "gen-fixed"
        events = [
            _event(offset=0, regime="I0", generation_id=gen),
            _event(offset=10, regime="I1", generation_id=gen),
            _event(offset=20, regime="I2", generation_id=gen),
            _event(offset=30, regime="I0", generation_id=gen),
            _event(offset=40, regime="I1", generation_id=gen),
            _event(offset=50, regime="I3", generation_id=gen),
            _event(offset=60, regime="I0", generation_id=gen),
            _event(offset=70, regime="I1", generation_id=gen),
            _event(offset=80, regime="I2", generation_id=gen),
        ]
        report = evaluate_markov_order(events, generation_id=gen)
        assert report.sufficient_samples
        assert report.triple_count >= 3

    def test_split_events_by_ci_commit(self):
        gen = compute_manifold_generation_id()
        events = [
            _event(offset=0, regime="I0", generation_id=gen, kind="ci_lattice", snapshot_id="ci-1", lossy=False),
            _event(offset=10, regime="I1", generation_id=gen),
            _event(offset=20, regime="I0", generation_id=gen, kind="ci_lattice", snapshot_id="ci-2", lossy=False),
            _event(offset=30, regime="I2", generation_id=gen),
        ]
        blocks = split_events_by_ci_commit(events)
        assert len(blocks) == 2
        assert blocks[0][0] == "ci-1"
        assert blocks[1][0] == "ci-2"

    def test_stationarity_stable_kernel(self):
        gen = "gen-fixed"
        baseline = [
            _event(offset=0, regime="I0", generation_id=gen, kind="ci_lattice", snapshot_id="ci-a", lossy=False),
            _event(offset=10, regime="I0", generation_id=gen),
            _event(offset=20, regime="I1", generation_id=gen),
            _event(offset=30, regime="I0", generation_id=gen),
        ]
        current = [
            _event(offset=40, regime="I0", generation_id=gen, kind="ci_lattice", snapshot_id="ci-b", lossy=False),
            _event(offset=50, regime="I0", generation_id=gen),
            _event(offset=60, regime="I1", generation_id=gen),
            _event(offset=70, regime="I0", generation_id=gen),
        ]
        report = evaluate_kernel_stationarity(
            baseline,
            current,
            generation_id=gen,
            baseline_commit_id="ci-a",
            current_commit_id="ci-b",
        )
        assert report.sufficient_samples
        assert report.kernel_stable
        assert report.classification == "stable_regime_dynamics"

    def test_kl_divergence_zero_for_identical_kernels(self):
        gen = "gen-fixed"
        events = [
            _event(offset=0, regime="I0", generation_id=gen),
            _event(offset=10, regime="I1", generation_id=gen),
            _event(offset=20, regime="I0", generation_id=gen),
            _event(offset=30, regime="I1", generation_id=gen),
        ]
        matrix = build_transition_matrix(events, generation_id=gen)
        assert matrix is not None
        kl = compute_kl_divergence_rate(matrix, matrix, events=events)
        assert kl.kl_global == 0.0

    def test_baseline_store_roundtrip(self, tmp_path: Path):
        gen = "gen-fixed"
        events = [
            _event(offset=0, regime="I0", generation_id=gen),
            _event(offset=10, regime="I1", generation_id=gen),
            _event(offset=20, regime="I0", generation_id=gen),
        ]
        matrix = build_transition_matrix(events, generation_id=gen)
        assert matrix is not None
        store = MarkovBaselineStore(tmp_path / "baseline.json")
        store.save(commit_id="ci-1", generation_id=gen, matrix=matrix)
        reloaded = MarkovBaselineStore(tmp_path / "baseline.json")
        assert reloaded.commit_id == "ci-1"
        assert reloaded.generation_id == gen
        assert reloaded.transition_matrix == matrix.probabilities

    def test_build_report_integration(self, tmp_path: Path):
        ci_store = ArbitrationTelemetryStore(tmp_path / "ci.json")
        ci_store.record_ci_lattice(build_canonical_fixture(), persist=True)
        ci_store.record_ci_lattice(build_canonical_fixture(), persist=True)
        report = build_markov_validation_report(
            ci_store=ci_store,
            baseline_store=MarkovBaselineStore(tmp_path / "baseline.json"),
            update_baseline=True,
        )
        assert report.version == "v1"
        assert report.commit_blocks >= 2

    def test_ci_diagnostic_step(self, tmp_path: Path, monkeypatch):
        from persona_ai.diagnostics.manifold_ci import check_markov_validation_diagnostic

        ci_path = tmp_path / "ci.json"
        baseline_path = tmp_path / "baseline.json"
        monkeypatch.setattr(
            "persona_ai.diagnostics.markov_validation.DEFAULT_BASELINE_PATH",
            baseline_path,
        )
        ci_store = ArbitrationTelemetryStore(ci_path)
        ci_store.record_ci_lattice(build_canonical_fixture(), persist=True)
        step = check_markov_validation_diagnostic(update_baseline=False)
        assert step.status in ("PASS", "SKIP")
        assert step.exit_code == 0
        assert step.step == "markov_validation"
