"""Phase D.2 — metastability detection tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from persona_ai.diagnostics.manifold_dynamics import (
    ALL_REGIMES,
    ManifoldEvent,
    RegimeHalfLifeReport,
    TransitionMatrix,
    build_transition_matrix,
)
from persona_ai.diagnostics.metastability import (
    MetastabilityBaselineStore,
    analyze_critical_cascade,
    analyze_spectral_gap,
    build_metastability_report,
    compute_boundary_early_warning,
    compute_quasi_stationary_distribution,
    extract_metastable_basins,
    find_transition_bottlenecks,
)


def _iso(offset: int = 0) -> str:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset)
    return base.isoformat()


def _events_alternating(gen: str = "gen-a", n: int = 8) -> list[ManifoldEvent]:
    events: list[ManifoldEvent] = []
    for index in range(n):
        events.append(
            ManifoldEvent(
                timestamp=_iso(index * 10),
                invariant_class="I0" if index % 2 == 0 else "I1",
                generation_id=gen,
                d_effective=0.1,
                anchor_density=0.0,
                source="runtime",
                event_kind="regime_change",
                snapshot_id=f"s-{index}",
            )
        )
    return events


def _matrix_from_events(events: list[ManifoldEvent]) -> TransitionMatrix:
    matrix = build_transition_matrix(events, generation_id="gen-a")
    assert matrix is not None
    return matrix


class TestMetastability:
    def test_spectral_gap_positive(self):
        matrix = _matrix_from_events(_events_alternating())
        spectral = analyze_spectral_gap(matrix)
        assert 0.0 <= spectral.spectral_gap <= 1.0
        assert spectral.mixing_time_proxy >= 1.0

    def test_metastable_basins_extracted(self):
        matrix = _matrix_from_events(_events_alternating(n=10))
        basins = extract_metastable_basins(matrix)
        assert basins
        assert all(basin.regimes for basin in basins)

    def test_bottlenecks_ranked_by_energy(self):
        matrix = _matrix_from_events(_events_alternating(n=10))
        bottlenecks = find_transition_bottlenecks(matrix)
        if len(bottlenecks) >= 2:
            assert bottlenecks[0].energy >= bottlenecks[1].energy

    def test_quasi_stationary_excludes_boundary(self):
        matrix = _matrix_from_events(_events_alternating(n=8))
        quasi = compute_quasi_stationary_distribution(matrix)
        assert "I5" not in quasi.quasi_stationary
        assert "I6" not in quasi.quasi_stationary
        assert abs(sum(quasi.quasi_stationary.values()) - 1.0) < 0.01

    def test_critical_cascade_report(self):
        counts = {regime: {target: 1.0 for target in ALL_REGIMES} for regime in ALL_REGIMES}
        counts["I2"]["I4"] = 5.0
        counts["I4"]["I5"] = 5.0
        counts["I4"]["I4"] = 8.0
        probabilities = {
            source: {
                target: counts[source][target] / sum(counts[source].values()) for target in ALL_REGIMES
            }
            for source in ALL_REGIMES
        }
        energy = {
            source: {target: 0.0 if probabilities[source][target] > 0.2 else 2.0 for target in ALL_REGIMES}
            for source in ALL_REGIMES
        }
        matrix = TransitionMatrix(
            generation_id="gen-a",
            counts=counts,
            probabilities=probabilities,
            energy=energy,
            sample_transitions=20,
        )
        half_life = RegimeHalfLifeReport(half_life_events={"I4": 6.0}, half_life_seconds={}, segment_count=1)
        cascade = analyze_critical_cascade(matrix, half_life)
        assert cascade.path_probability > 0.0
        assert cascade.cascade == ["I2", "I4", "I5"]

    def test_boundary_warning_drivers(self):
        matrix = _matrix_from_events(_events_alternating(n=8))
        spectral = analyze_spectral_gap(matrix, baseline_gap=0.9)
        cascade = analyze_critical_cascade(matrix, RegimeHalfLifeReport({}, {}, 0))
        warning = compute_boundary_early_warning(matrix, spectral=spectral, cascade=cascade)
        assert isinstance(warning.warning_active, bool)
        assert isinstance(warning.drivers, list)

    def test_baseline_store_roundtrip(self, tmp_path: Path):
        store = MetastabilityBaselineStore(tmp_path / "meta.json")
        store.save(spectral_gap=0.42, boundary_approach_score=0.03, generation_id="gen-a")
        reloaded = MetastabilityBaselineStore(tmp_path / "meta.json")
        assert reloaded.spectral_gap == 0.42
        assert reloaded.generation_id == "gen-a"

    def test_build_report_insufficient_samples(self, tmp_path: Path):
        report = build_metastability_report(
            baseline_store=MetastabilityBaselineStore(tmp_path / "meta.json"),
        )
        assert report.version == "v1"
        assert report.sufficient_samples is False
