"""Phase D.3.1 — forecast verification tests."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from persona_ai.diagnostics.forecast_verification import (
    ForecastVerificationStore,
    StoredForecast,
    build_forecast_verification_report,
    build_lineage_report,
    classify_forecast_quality,
    score_forecast_record,
    verify_pending_forecasts,
)
from persona_ai.diagnostics.manifold_dynamics import ManifoldEvent


def _iso(offset: int = 0) -> str:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset)
    return base.isoformat()


def _events(regimes: list[str], gen: str = "gen-a") -> list[ManifoldEvent]:
    return [
        ManifoldEvent(
            timestamp=_iso(index * 10),
            invariant_class=regime,
            generation_id=gen,
            d_effective=0.1,
            anchor_density=0.0,
            source="runtime",
            event_kind="regime_change",
            snapshot_id=f"s-{index}",
        )
        for index, regime in enumerate(regimes)
    ]


def _stored(**overrides) -> StoredForecast:
    base = dict(
        forecast_id="f1",
        forecast_origin="test",
        issued_at=_iso(0),
        origin_timestamp=_iso(0),
        origin_regime="I0",
        generation_id="gen-a",
        horizon=2,
        probabilities={"I0": 0.7, "I1": 0.2, "I2": 0.1, "I3": 0.0, "I4": 0.0, "I5": 0.0, "I6": 0.0},
        p_boundary_within=0.1,
        confidence_band="HIGH",
        forecast_status="CLEAR",
    )
    base.update(overrides)
    return StoredForecast(**base)


class TestForecastVerification:
    def test_brier_and_log_score_with_lineage(self):
        record = score_forecast_record(_stored(), actual_regime="I0", boundary_hit=False)
        assert record.top1_hit
        assert record.origin_regime == "I0"
        assert record.generation_id == "gen-a"
        assert record.horizon == 2
        assert record.brier_score < 0.2

    def test_boundary_brier(self):
        record = score_forecast_record(
            _stored(origin_regime="I2", p_boundary_within=0.8),
            actual_regime="I5",
            boundary_hit=True,
        )
        assert record.boundary_brier < 0.1

    def test_verify_pending_at_horizon(self, tmp_path: Path):
        store = ForecastVerificationStore(tmp_path / "verify.json")
        store.pending.append(_stored(horizon=2))
        events = _events(["I0", "I1", "I2", "I3"])
        verified = verify_pending_forecasts(events, store, persist=False)
        assert len(verified) == 1
        assert verified[0].actual_regime == "I2"
        assert len(store.pending) == 0

    def test_lineage_group_by_origin_regime(self, tmp_path: Path):
        store = ForecastVerificationStore(tmp_path / "verify.json")
        store.verified.extend(
            [
                score_forecast_record(
                    _stored(origin_regime="I2", forecast_id="a"),
                    actual_regime="I2",
                    boundary_hit=False,
                ),
                score_forecast_record(
                    _stored(origin_regime="I2", forecast_id="b"),
                    actual_regime="I3",
                    boundary_hit=False,
                ),
                score_forecast_record(
                    _stored(origin_regime="I4", forecast_id="c", p_boundary_within=0.9),
                    actual_regime="I5",
                    boundary_hit=True,
                ),
            ]
        )
        lineage = build_lineage_report(store.verified)
        i2 = next(item for item in lineage.by_origin_regime if item.group_key == "I2")
        i4 = next(item for item in lineage.by_origin_regime if item.group_key == "I4")
        assert i2.count == 2
        assert i4.count == 1
        assert i4.mean_brier > i2.mean_brier

    def test_lineage_group_by_horizon(self):
        records = [
            score_forecast_record(_stored(horizon=3, forecast_id="h1"), actual_regime="I0", boundary_hit=False),
            score_forecast_record(_stored(horizon=5, forecast_id="h2"), actual_regime="I1", boundary_hit=False),
        ]
        lineage = build_lineage_report(records)
        horizons = {item.group_key for item in lineage.by_horizon}
        assert "3" in horizons
        assert "5" in horizons

    def test_quality_unverified_without_history(self):
        assert classify_forecast_quality(
            verified_count=2,
            mean_brier=0.1,
            calibration_error=0.05,
            overconfidence_index=0.0,
        ) == "UNVERIFIED"

    def test_quality_overconfident(self):
        assert classify_forecast_quality(
            verified_count=10,
            mean_brier=0.4,
            calibration_error=0.2,
            overconfidence_index=0.25,
        ) == "OVERCONFIDENT"

    def test_build_report_includes_lineage(self, tmp_path: Path):
        store = ForecastVerificationStore(tmp_path / "verify.json")
        store.verified.append(
            score_forecast_record(_stored(), actual_regime="I0", boundary_hit=False)
        )
        report = build_forecast_verification_report(store=store)
        assert report.lineage.by_origin_regime
        assert report.matrix.generation_id
        assert report.validation_window.window_open
        assert report.read_only_downstream is True

    def test_verification_matrix_regime_horizon(self, tmp_path: Path):
        from persona_ai.diagnostics.forecast_verification import build_forecast_verification_matrix

        records = [
            score_forecast_record(
                _stored(
                    origin_regime="I2",
                    horizon=5,
                    forecast_id="a",
                    probabilities={
                        "I0": 0.05,
                        "I1": 0.05,
                        "I2": 0.7,
                        "I3": 0.1,
                        "I4": 0.05,
                        "I5": 0.03,
                        "I6": 0.02,
                    },
                ),
                actual_regime="I2",
                boundary_hit=False,
            ),
            score_forecast_record(
                _stored(
                    origin_regime="I2",
                    horizon=5,
                    forecast_id="b",
                    probabilities={
                        "I0": 0.05,
                        "I1": 0.05,
                        "I2": 0.7,
                        "I3": 0.1,
                        "I4": 0.05,
                        "I5": 0.03,
                        "I6": 0.02,
                    },
                ),
                actual_regime="I2",
                boundary_hit=False,
            ),
            score_forecast_record(
                _stored(
                    origin_regime="I2",
                    horizon=5,
                    forecast_id="c",
                    probabilities={
                        "I0": 0.05,
                        "I1": 0.05,
                        "I2": 0.7,
                        "I3": 0.1,
                        "I4": 0.05,
                        "I5": 0.03,
                        "I6": 0.02,
                    },
                ),
                actual_regime="I2",
                boundary_hit=False,
            ),
            score_forecast_record(
                _stored(origin_regime="I4", horizon=5, forecast_id="d", p_boundary_within=0.9),
                actual_regime="I5",
                boundary_hit=True,
            ),
        ]
        matrix = build_forecast_verification_matrix(records)
        i2_h5 = next(
            cell for cell in matrix.cells if cell.origin_regime == "I2" and cell.horizon == 5
        )
        assert i2_h5.count == 3
        assert i2_h5.top1_hit_rate == 1.0
        assert "I2" in matrix.regimes
        assert 5 in matrix.horizons

    def test_multi_generation_blocks_naive_global_quality(self, tmp_path: Path):
        from persona_ai.diagnostics.forecast_verification import _resolve_generation_scope

        store = ForecastVerificationStore(tmp_path / "verify.json")
        for index in range(3):
            store.verified.append(
                score_forecast_record(
                    _stored(generation_id="gen-a", forecast_id=f"a{index}"),
                    actual_regime="I0",
                    boundary_hit=False,
                )
            )
        for index in range(3):
            store.verified.append(
                score_forecast_record(
                    _stored(generation_id="gen-b", forecast_id=f"b{index}"),
                    actual_regime="I5",
                    boundary_hit=True,
                )
            )
        scope = _resolve_generation_scope(store.verified)
        assert scope.multi_generation_detected
        assert scope.cross_generation_aggregate_blocked
        report = build_forecast_verification_report(store=store)
        assert report.forecast_quality == "UNVERIFIED"
        assert report.generation_scope.generation_count == 2

    def test_matrix_format_includes_generation(self):
        from persona_ai.diagnostics.forecast_verification import (
            ForecastVerificationMatrix,
            format_forecast_verification_matrix,
        )

        text = format_forecast_verification_matrix(
            ForecastVerificationMatrix("gen_abc123", [1, 5, 10], [], [], [])
        )
        assert "gen_abc123" in text
        assert "read-only" in text
        assert "n>=3" in text

    def test_record_forecast_ignores_quality(self, tmp_path: Path):
        """record_forecast must not read forecast_quality from report."""
        from persona_ai.diagnostics.regime_forecast import (
            BoundaryHorizonProfile,
            CalibratedConfidence,
            ForecastValidity,
            HorizonForecast,
            RegimeForecastReport,
            TransitionUncertainty,
        )

        report = RegimeForecastReport(
            version="v1.1",
            current_regime="I0",
            forecast=HorizonForecast(
                5,
                {"I0": 1.0, "I1": 0.0, "I2": 0.0, "I3": 0.0, "I4": 0.0, "I5": 0.0, "I6": 0.0},
                0.0,
                0.0,
                0.0,
            ),
            boundary_profile=BoundaryHorizonProfile([], {}, {}),
            uncertainty=TransitionUncertainty(10.0, {}, {}, 0.1),
            validity=ForecastValidity("gen-a", True, True, False, True, False),
            confidence=CalibratedConfidence("HIGH", "CLEAR", []),
            forecast_quality="OVERCONFIDENT",
        )
        store = ForecastVerificationStore(tmp_path / "verify.json")
        stored = store.record_forecast(report=report, persist=False)
        assert stored is not None
        assert stored.origin_regime == "I0"
