"""Phase D.3 — probabilistic regime forecast tests."""

from datetime import datetime, timedelta, timezone

from persona_ai.diagnostics.manifold_dynamics import (
    ALL_REGIMES,
    ManifoldEvent,
    TransitionMatrix,
    build_transition_matrix,
)
from persona_ai.diagnostics.regime_forecast import (
    build_regime_forecast_report,
    calibrate_forecast_confidence,
    compute_boundary_horizon_profile,
    estimate_transition_uncertainty,
    forecast_regime_distribution,
    ForecastValidity,
    TransitionUncertainty,
)


def _iso(offset: int = 0) -> str:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset)
    return base.isoformat()


def _alternating_events(n: int = 10, gen: str = "gen-a") -> list[ManifoldEvent]:
    return [
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
        for index in range(n)
    ]


def _matrix_with_boundary_path() -> TransitionMatrix:
    counts = {regime: {target: 1.0 for target in ALL_REGIMES} for regime in ALL_REGIMES}
    counts["I0"]["I2"] = 8.0
    counts["I2"]["I4"] = 6.0
    counts["I4"]["I5"] = 6.0
    counts["I4"]["I4"] = 4.0
    counts["I5"]["I5"] = 10.0
    probabilities = {
        source: {target: counts[source][target] / sum(counts[source].values()) for target in ALL_REGIMES}
        for source in ALL_REGIMES
    }
    energy = {
        source: {target: 0.0 for target in ALL_REGIMES} for source in ALL_REGIMES
    }
    return TransitionMatrix(
        generation_id="gen-a",
        counts=counts,
        probabilities=probabilities,
        energy=energy,
        sample_transitions=40,
    )


class TestRegimeForecast:
    def test_horizon_distribution_sums_to_one(self):
        matrix = build_transition_matrix(_alternating_events(), generation_id="gen-a")
        assert matrix is not None
        forecast = forecast_regime_distribution(matrix, current_regime="I0", horizon=5)
        total = sum(forecast.probabilities.values())
        assert abs(total - 1.0) < 0.01

    def test_boundary_within_exceeds_exact(self):
        matrix = _matrix_with_boundary_path()
        profile = compute_boundary_horizon_profile(matrix, current_regime="I0", horizons=[1, 5, 10])
        assert profile.p_boundary_within[5] >= profile.p_boundary_exact.get(1, 0.0)
        assert profile.p_boundary_within[10] >= profile.p_boundary_within[5]

    def test_transition_uncertainty_intervals(self):
        matrix = build_transition_matrix(_alternating_events(), generation_id="gen-a")
        assert matrix is not None
        uncertainty = estimate_transition_uncertainty(matrix)
        assert uncertainty.effective_sample_size > 0
        assert uncertainty.max_interval_width >= 0.0

    def test_confidence_downgrade_on_invalid_order(self):
        validity = ForecastValidity(
            generation_id="gen-a",
            markov_order_valid=False,
            kernel_stable=True,
            lossy_observation=True,
            sufficient_samples=True,
            structural_shift=False,
        )
        confidence = calibrate_forecast_confidence(
            validity=validity,
            uncertainty=TransitionUncertainty(10.0, {}, {}, 0.4),
            validation=None,
            metastability=None,
            p_boundary_within=0.05,
        )
        assert confidence.confidence_band == "LOW"
        assert "markov_order_violated" in confidence.downgrade_reasons

    def test_confidence_withhold_on_insufficient_samples(self):
        validity = ForecastValidity(
            generation_id="gen-a",
            markov_order_valid=True,
            kernel_stable=True,
            lossy_observation=False,
            sufficient_samples=False,
            structural_shift=False,
        )
        confidence = calibrate_forecast_confidence(
            validity=validity,
            uncertainty=TransitionUncertainty(0.0, {}, {}, 1.0),
            validation=None,
            metastability=None,
            p_boundary_within=0.0,
        )
        assert confidence.forecast_status == "WITHHOLD"

    def test_cascade_probability_positive(self):
        matrix = _matrix_with_boundary_path()
        forecast = forecast_regime_distribution(matrix, current_regime="I0", horizon=5)
        assert forecast.p_cascade_i4_i5 > 0.0

    def test_build_report_insufficient(self):
        report = build_regime_forecast_report()
        assert report.version == "v1.1"
        assert report.confidence.forecast_status in ("WITHHOLD", "MONITOR", "CLEAR", "CAUTION")

    def test_monitor_status_on_elevated_boundary(self):
        validity = ForecastValidity(
            generation_id="gen-a",
            markov_order_valid=True,
            kernel_stable=True,
            lossy_observation=False,
            sufficient_samples=True,
            structural_shift=False,
        )
        confidence = calibrate_forecast_confidence(
            validity=validity,
            uncertainty=TransitionUncertainty(50.0, {}, {}, 0.1),
            validation=None,
            metastability=None,
            p_boundary_within=0.15,
        )
        assert confidence.forecast_status == "MONITOR"
