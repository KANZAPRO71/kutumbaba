"""Phase D.3.1 — forecast verification against observed regime outcomes.

Separates forecast_status (operational warning) from forecast_quality
(calibration against actual outcomes). Diagnostic-only — no authority path.

Downstream read-only contract (NEVER violate):
  forecast → outcome → score → quality
  quality MUST NOT feed back into forecast generation.

Pipeline:
  forecast → persist → wait for observed regime → score → calibration report
"""

from __future__ import annotations

import json
import math
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from persona_ai.diagnostics.manifold_dynamics import (
    ALL_REGIMES,
    ManifoldEvent,
    extract_event_stream,
)
from persona_ai.diagnostics.regime_forecast import (
    BOUNDARY_REGIMES,
    RegimeForecastReport,
)

VERIFICATION_VERSION = "v1.2"
DEFAULT_STORE_PATH = Path(".persona_ai/forecast_verification.json")
MIN_VERIFIED_FOR_QUALITY = 5
MIN_GROUP_FOR_QUALITY = 3
CALIBRATION_TOLERANCE = 0.08
BRIER_CALIBRATED_MAX = 0.35
TOP_K = 3
EPS = 1e-12
MATRIX_HORIZONS = (1, 5, 10)
QUALITY_ABBREV: dict[ForecastQuality, str] = {
    "CALIBRATED": "CAL",
    "OVERCONFIDENT": "OVER",
    "UNDERCONFIDENT": "UNDER",
    "UNVERIFIED": "UNVER",
}

ForecastQuality = Literal["UNVERIFIED", "CALIBRATED", "OVERCONFIDENT", "UNDERCONFIDENT"]
LineageGroupType = Literal[
    "generation_id",
    "origin_regime",
    "horizon",
    "forecast_status",
    "confidence_band",
]


@dataclass
class StoredForecast:
    forecast_id: str
    forecast_origin: str
    issued_at: str
    origin_timestamp: str
    origin_regime: str
    generation_id: str
    horizon: int
    probabilities: dict[str, float]
    p_boundary_within: float
    confidence_band: str
    forecast_status: str
    verified: bool = False
    verified_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerifiedForecastRecord:
    """Scored forecast with full lineage for grouped analysis."""

    forecast_id: str
    generation_id: str
    origin_regime: str
    horizon: int
    forecast_status: str
    confidence_band: str
    forecast_origin: str
    verified_at: str
    brier_score: float
    log_score: float
    top1_hit: bool
    top3_hit: bool
    boundary_brier: float
    predicted_top_regime: str
    actual_regime: str
    boundary_hit: bool
    predicted_boundary_prob: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LineageGroupSummary:
    group_type: LineageGroupType
    group_key: str
    count: int
    mean_brier: float
    mean_log_score: float
    mean_boundary_brier: float
    top1_hit_rate: float
    top3_hit_rate: float
    overconfidence_index: float
    group_quality: ForecastQuality

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ForecastLineageReport:
    by_generation_id: list[LineageGroupSummary]
    by_origin_regime: list[LineageGroupSummary]
    by_horizon: list[LineageGroupSummary]
    by_forecast_status: list[LineageGroupSummary]
    by_confidence_band: list[LineageGroupSummary]
    boundary_by_origin_regime: list[LineageGroupSummary]

    def to_dict(self) -> dict[str, Any]:
        return {
            "by_generation_id": [item.to_dict() for item in self.by_generation_id],
            "by_origin_regime": [item.to_dict() for item in self.by_origin_regime],
            "by_horizon": [item.to_dict() for item in self.by_horizon],
            "by_forecast_status": [item.to_dict() for item in self.by_forecast_status],
            "by_confidence_band": [item.to_dict() for item in self.by_confidence_band],
            "boundary_by_origin_regime": [item.to_dict() for item in self.boundary_by_origin_regime],
        }


@dataclass
class MatrixCell:
    origin_regime: str
    horizon: int
    count: int
    group_quality: ForecastQuality
    mean_brier: float
    mean_log_score: float
    mean_boundary_brier: float
    top1_hit_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RegimeScoreRow:
    origin_regime: str
    count: int
    mean_brier: float
    mean_log_score: float
    mean_boundary_brier: float
    group_quality: ForecastQuality
    reliability_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ForecastVerificationMatrix:
    """Regime × horizon quality grid — evidence panel, read-only."""

    generation_id: str
    horizons: list[int]
    regimes: list[str]
    cells: list[MatrixCell]
    regime_scores: list[RegimeScoreRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation_id": self.generation_id,
            "horizons": self.horizons,
            "regimes": self.regimes,
            "cells": [cell.to_dict() for cell in self.cells],
            "regime_scores": [row.to_dict() for row in self.regime_scores],
        }


@dataclass
class CalibrationBin:
    bin_center: float
    mean_predicted: float
    observed_frequency: float
    count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GenerationScope:
    """Global quality and matrix are scoped to one generation — never naively pooled."""

    active_generation_id: str
    generation_count: int
    multi_generation_detected: bool
    cross_generation_aggregate_blocked: bool
    generation_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationWindow:
    verified_count: int
    pending_count: int
    min_required_for_global_quality: int
    min_required_for_group_quality: int
    window_open: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ForecastVerificationReport:
    version: str
    forecast_quality: ForecastQuality
    verified_count: int
    pending_count: int
    mean_brier: float
    mean_log_score: float
    top1_hit_rate: float
    top3_hit_rate: float
    mean_boundary_brier: float
    calibration_error: float
    overconfidence_index: float
    calibration_bins: list[CalibrationBin]
    recent_records: list[VerifiedForecastRecord]
    lineage: ForecastLineageReport
    matrix: ForecastVerificationMatrix
    generation_scope: GenerationScope
    validation_window: ValidationWindow
    read_only_downstream: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_version": self.version,
            "forecast_quality": self.forecast_quality,
            "verified_count": self.verified_count,
            "pending_count": self.pending_count,
            "mean_brier": self.mean_brier,
            "mean_log_score": self.mean_log_score,
            "top1_hit_rate": self.top1_hit_rate,
            "top3_hit_rate": self.top3_hit_rate,
            "mean_boundary_brier": self.mean_boundary_brier,
            "calibration_error": self.calibration_error,
            "overconfidence_index": self.overconfidence_index,
            "calibration_bins": [item.to_dict() for item in self.calibration_bins],
            "recent_records": [item.to_dict() for item in self.recent_records],
            "lineage": self.lineage.to_dict(),
            "matrix": self.matrix.to_dict(),
            "generation_scope": self.generation_scope.to_dict(),
            "validation_window": self.validation_window.to_dict(),
            "read_only_downstream": self.read_only_downstream,
        }


@dataclass
class ForecastVerificationStore:
    path: Path = field(default_factory=lambda: DEFAULT_STORE_PATH)
    pending: list[StoredForecast] = field(default_factory=list)
    verified: list[VerifiedForecastRecord] = field(default_factory=list)
    history: list[StoredForecast] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.pending = [StoredForecast(**row) for row in raw.get("pending", [])]
        self.history = [StoredForecast(**row) for row in raw.get("history", [])]
        self.verified = []
        for row in raw.get("verified", []):
            self.verified.append(
                VerifiedForecastRecord(
                    forecast_id=row["forecast_id"],
                    generation_id=row.get("generation_id", ""),
                    origin_regime=row.get("origin_regime", "unknown"),
                    horizon=int(row.get("horizon", 0)),
                    forecast_status=row.get("forecast_status", "CLEAR"),
                    confidence_band=row.get("confidence_band", "MEDIUM"),
                    forecast_origin=row.get("forecast_origin", "unknown"),
                    verified_at=row.get("verified_at", ""),
                    brier_score=row["brier_score"],
                    log_score=row["log_score"],
                    top1_hit=row["top1_hit"],
                    top3_hit=row["top3_hit"],
                    boundary_brier=row["boundary_brier"],
                    predicted_top_regime=row.get("predicted_top_regime", ""),
                    actual_regime=row.get("actual_regime", ""),
                    boundary_hit=row.get("boundary_hit", False),
                    predicted_boundary_prob=row.get("predicted_boundary_prob", 0.0),
                )
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "verification_version": VERIFICATION_VERSION,
            "pending": [item.to_dict() for item in self.pending],
            "verified": [item.to_dict() for item in self.verified[-500:]],
            "history": [item.to_dict() for item in self.history[-500:]],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def record_forecast(
        self,
        *,
        report: RegimeForecastReport,
        forecast_origin: str = "ci",
        origin_timestamp: str | None = None,
        persist: bool = True,
    ) -> StoredForecast | None:
        """Record forecast for later verification — never reads forecast_quality."""
        if not report.validity.sufficient_samples:
            return None
        if report.confidence.forecast_status == "WITHHOLD":
            return None

        origin_ts = origin_timestamp or datetime.now(timezone.utc).isoformat()
        stored = StoredForecast(
            forecast_id=str(uuid.uuid4()),
            forecast_origin=forecast_origin,
            issued_at=datetime.now(timezone.utc).isoformat(),
            origin_timestamp=origin_ts,
            origin_regime=report.current_regime,
            generation_id=report.validity.generation_id or "",
            horizon=report.forecast.horizon,
            probabilities=dict(report.forecast.probabilities),
            p_boundary_within=report.forecast.p_boundary_within,
            confidence_band=report.confidence.confidence_band,
            forecast_status=report.confidence.forecast_status,
        )
        self.pending.append(stored)
        self.history.append(stored)
        if persist:
            self.save()
        return stored


def _parse_ts(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _future_events(
    events: list[ManifoldEvent],
    *,
    after_timestamp: str,
    generation_id: str,
) -> list[ManifoldEvent]:
    origin = _parse_ts(after_timestamp)
    return [
        event
        for event in events
        if event.generation_id == generation_id and _parse_ts(event.timestamp) > origin
    ]


def score_forecast_record(
    stored: StoredForecast,
    *,
    actual_regime: str,
    boundary_hit: bool,
    verified_at: str | None = None,
) -> VerifiedForecastRecord:
    """Proper scoring rules with lineage preserved for grouped analysis."""
    probabilities = stored.probabilities
    actual_prob = max(probabilities.get(actual_regime, 0.0), EPS)
    brier = sum(
        (probabilities.get(regime, 0.0) - (1.0 if regime == actual_regime else 0.0)) ** 2
        for regime in ALL_REGIMES
    )
    log_score = -math.log(actual_prob)
    ranked = sorted(probabilities.items(), key=lambda item: -item[1])
    top1 = ranked[0][0] if ranked else actual_regime
    top3 = {regime for regime, _ in ranked[:TOP_K]}
    boundary_brier = (stored.p_boundary_within - (1.0 if boundary_hit else 0.0)) ** 2
    return VerifiedForecastRecord(
        forecast_id=stored.forecast_id,
        generation_id=stored.generation_id,
        origin_regime=stored.origin_regime,
        horizon=stored.horizon,
        forecast_status=stored.forecast_status,
        confidence_band=stored.confidence_band,
        forecast_origin=stored.forecast_origin,
        verified_at=verified_at or datetime.now(timezone.utc).isoformat(),
        brier_score=round(brier, 6),
        log_score=round(log_score, 6),
        top1_hit=top1 == actual_regime,
        top3_hit=actual_regime in top3,
        boundary_brier=round(boundary_brier, 6),
        predicted_top_regime=top1,
        actual_regime=actual_regime,
        boundary_hit=boundary_hit,
        predicted_boundary_prob=stored.p_boundary_within,
    )


def verify_pending_forecasts(
    events: list[ManifoldEvent],
    store: ForecastVerificationStore,
    *,
    persist: bool = True,
) -> list[VerifiedForecastRecord]:
    """Match pending forecasts to observed regimes at horizon."""
    newly_verified: list[VerifiedForecastRecord] = []
    still_pending: list[StoredForecast] = []

    for stored in store.pending:
        if not stored.generation_id:
            still_pending.append(stored)
            continue
        future = _future_events(
            events,
            after_timestamp=stored.origin_timestamp,
            generation_id=stored.generation_id,
        )
        if len(future) < stored.horizon:
            still_pending.append(stored)
            continue

        actual = future[stored.horizon - 1].invariant_class
        boundary_hit = any(
            event.invariant_class in BOUNDARY_REGIMES for event in future[: stored.horizon]
        )
        record = score_forecast_record(stored, actual_regime=actual, boundary_hit=boundary_hit)
        stored.verified = True
        stored.verified_at = record.verified_at
        newly_verified.append(record)
        store.verified.append(record)

    store.pending = still_pending
    if persist:
        store.save()
    return newly_verified


def _aggregate_records(records: list[VerifiedForecastRecord]) -> dict[str, float]:
    count = len(records)
    if count == 0:
        return {
            "mean_brier": 0.0,
            "mean_log_score": 0.0,
            "mean_boundary_brier": 0.0,
            "top1_hit_rate": 0.0,
            "top3_hit_rate": 0.0,
            "overconfidence_index": 0.0,
        }
    mean_brier = sum(item.brier_score for item in records) / count
    mean_log = sum(item.log_score for item in records) / count
    mean_boundary = sum(item.boundary_brier for item in records) / count
    top1 = sum(1.0 for item in records if item.top1_hit) / count
    top3 = sum(1.0 for item in records if item.top3_hit) / count
    mean_pred = sum(1.0 - item.brier_score / 2.0 for item in records) / count
    return {
        "mean_brier": round(mean_brier, 6),
        "mean_log_score": round(mean_log, 6),
        "mean_boundary_brier": round(mean_boundary, 6),
        "top1_hit_rate": round(top1, 6),
        "top3_hit_rate": round(top3, 6),
        "overconfidence_index": round(mean_pred - top1, 6),
    }


def classify_forecast_quality(
    *,
    verified_count: int,
    mean_brier: float,
    calibration_error: float,
    overconfidence_index: float,
    min_required: int = MIN_VERIFIED_FOR_QUALITY,
) -> ForecastQuality:
    if verified_count < min_required:
        return "UNVERIFIED"
    if overconfidence_index > 0.12:
        return "OVERCONFIDENT"
    if overconfidence_index < -0.12:
        return "UNDERCONFIDENT"
    if mean_brier <= BRIER_CALIBRATED_MAX and calibration_error <= CALIBRATION_TOLERANCE:
        return "CALIBRATED"
    if calibration_error > CALIBRATION_TOLERANCE:
        return "OVERCONFIDENT"
    return "UNVERIFIED"


def _summarize_lineage_group(
    group_type: LineageGroupType,
    group_key: str,
    records: list[VerifiedForecastRecord],
) -> LineageGroupSummary:
    stats = _aggregate_records(records)
    bins = _calibration_bins_from_records(records)
    cal_error = _calibration_error(bins)
    quality = classify_forecast_quality(
        verified_count=len(records),
        mean_brier=stats["mean_brier"],
        calibration_error=cal_error,
        overconfidence_index=stats["overconfidence_index"],
        min_required=MIN_GROUP_FOR_QUALITY,
    )
    return LineageGroupSummary(
        group_type=group_type,
        group_key=group_key,
        count=len(records),
        mean_brier=stats["mean_brier"],
        mean_log_score=stats["mean_log_score"],
        mean_boundary_brier=stats["mean_boundary_brier"],
        top1_hit_rate=stats["top1_hit_rate"],
        top3_hit_rate=stats["top3_hit_rate"],
        overconfidence_index=stats["overconfidence_index"],
        group_quality=quality,
    )


def _group_records(
    records: list[VerifiedForecastRecord],
    group_type: LineageGroupType,
    key_fn,
) -> list[LineageGroupSummary]:
    buckets: dict[str, list[VerifiedForecastRecord]] = defaultdict(list)
    for record in records:
        buckets[str(key_fn(record))].append(record)
    summaries = [
        _summarize_lineage_group(group_type, key, bucket)
        for key, bucket in sorted(buckets.items())
    ]
    return [item for item in summaries if item.count > 0]


def build_lineage_report(records: list[VerifiedForecastRecord]) -> ForecastLineageReport:
    """Group verified forecasts to answer: bad forecasts come from what conditions?"""
    by_regime = _group_records(records, "origin_regime", lambda record: record.origin_regime)
    boundary_by_regime = [
        _summarize_lineage_group(
            "origin_regime",
            item.group_key,
            [record for record in records if record.origin_regime == item.group_key],
        )
        for item in by_regime
    ]
    for index, item in enumerate(boundary_by_regime):
        regime_records = [record for record in records if record.origin_regime == item.group_key]
        stats = _aggregate_records(regime_records)
        boundary_by_regime[index] = LineageGroupSummary(
            group_type="origin_regime",
            group_key=item.group_key,
            count=item.count,
            mean_brier=stats["mean_brier"],
            mean_log_score=stats["mean_log_score"],
            mean_boundary_brier=stats["mean_boundary_brier"],
            top1_hit_rate=stats["top1_hit_rate"],
            top3_hit_rate=stats["top3_hit_rate"],
            overconfidence_index=stats["overconfidence_index"],
            group_quality=classify_forecast_quality(
                verified_count=item.count,
                mean_brier=stats["mean_boundary_brier"],
                calibration_error=stats["mean_boundary_brier"],
                overconfidence_index=stats["overconfidence_index"],
                min_required=MIN_GROUP_FOR_QUALITY,
            ),
        )

    return ForecastLineageReport(
        by_generation_id=_group_records(
            records, "generation_id", lambda record: record.generation_id or "unknown"
        ),
        by_origin_regime=by_regime,
        by_horizon=_group_records(records, "horizon", lambda record: record.horizon),
        by_forecast_status=_group_records(
            records, "forecast_status", lambda record: record.forecast_status
        ),
        by_confidence_band=_group_records(
            records, "confidence_band", lambda record: record.confidence_band
        ),
        boundary_by_origin_regime=boundary_by_regime,
    )


def _calibration_bins_from_records(
    records: list[VerifiedForecastRecord],
    *,
    n_bins: int = 5,
) -> list[CalibrationBin]:
    if not records:
        return []
    bins: list[list[VerifiedForecastRecord]] = [[] for _ in range(n_bins)]
    for record in records:
        predicted_confidence = max(record.predicted_boundary_prob, 1.0 - record.brier_score / 2.0)
        index = min(n_bins - 1, int(predicted_confidence * n_bins))
        bins[index].append(record)

    result: list[CalibrationBin] = []
    for index, bucket in enumerate(bins):
        if not bucket:
            continue
        mean_predicted = sum(
            max(item.predicted_boundary_prob, 1.0 - item.brier_score / 2.0) for item in bucket
        ) / len(bucket)
        observed = sum(1.0 for item in bucket if item.top1_hit) / len(bucket)
        result.append(
            CalibrationBin(
                bin_center=round((index + 0.5) / n_bins, 4),
                mean_predicted=round(mean_predicted, 4),
                observed_frequency=round(observed, 4),
                count=len(bucket),
            )
        )
    return result


def _calibration_error(bins: list[CalibrationBin]) -> float:
    if not bins:
        return 1.0
    total = sum(item.count for item in bins)
    if total == 0:
        return 1.0
    error = sum(
        item.count * abs(item.mean_predicted - item.observed_frequency) for item in bins
    ) / total
    return round(error, 6)


def _empty_lineage() -> ForecastLineageReport:
    return ForecastLineageReport([], [], [], [], [], [])


def _empty_matrix() -> ForecastVerificationMatrix:
    return ForecastVerificationMatrix("unknown", list(MATRIX_HORIZONS), [], [], [])


def _empty_generation_scope() -> GenerationScope:
    return GenerationScope("unknown", 0, False, False, {})


def _generation_counts(records: list[VerifiedForecastRecord]) -> dict[str, int]:
    counts = Counter(record.generation_id or "unknown" for record in records)
    return dict(counts)


def _resolve_generation_scope(records: list[VerifiedForecastRecord]) -> GenerationScope:
    """Scope global metrics to dominant generation; block naive cross-gen pooling."""
    counts = _generation_counts(records)
    if not counts:
        return _empty_generation_scope()
    active_id = Counter(counts).most_common(1)[0][0]
    generation_count = len(counts)
    multi = generation_count > 1
    blocked = multi and any(
        generation_id != active_id and count >= MIN_GROUP_FOR_QUALITY
        for generation_id, count in counts.items()
    )
    return GenerationScope(
        active_generation_id=active_id,
        generation_count=generation_count,
        multi_generation_detected=multi,
        cross_generation_aggregate_blocked=blocked,
        generation_counts=counts,
    )


def _records_for_generation(
    records: list[VerifiedForecastRecord],
    generation_id: str,
) -> list[VerifiedForecastRecord]:
    return [record for record in records if (record.generation_id or "unknown") == generation_id]


def _display_generation_id(generation_id: str) -> str:
    if len(generation_id) <= 28:
        return generation_id
    return generation_id[:24] + "..."


def _quality_abbrev(quality: ForecastQuality) -> str:
    return QUALITY_ABBREV.get(quality, "UNVER")


def _dominant_generation_id(records: list[VerifiedForecastRecord]) -> str:
    if not records:
        return "unknown"
    counts = Counter(record.generation_id or "unknown" for record in records)
    generation_id, _ = counts.most_common(1)[0]
    return _display_generation_id(generation_id)


def _regimes_in_matrix(records: list[VerifiedForecastRecord]) -> list[str]:
    seen = {record.origin_regime for record in records}
    ordered = [regime for regime in ALL_REGIMES if regime in seen]
    for regime in sorted(seen):
        if regime not in ordered:
            ordered.append(regime)
    return ordered


def build_forecast_verification_matrix(
    records: list[VerifiedForecastRecord],
    *,
    generation_id: str | None = None,
) -> ForecastVerificationMatrix:
    """Regime × horizon grid scoped to one generation frame."""
    scope_id = generation_id
    if scope_id is None and records:
        scope_id = _resolve_generation_scope(records).active_generation_id
    scoped = _records_for_generation(records, scope_id) if scope_id else records
    horizons = list(MATRIX_HORIZONS)
    regimes = _regimes_in_matrix(scoped)
    cells: list[MatrixCell] = []

    for regime in regimes:
        for horizon in horizons:
            bucket = [
                record
                for record in scoped
                if record.origin_regime == regime and record.horizon == horizon
            ]
            if not bucket:
                cells.append(
                    MatrixCell(
                        origin_regime=regime,
                        horizon=horizon,
                        count=0,
                        group_quality="UNVERIFIED",
                        mean_brier=0.0,
                        mean_log_score=0.0,
                        mean_boundary_brier=0.0,
                        top1_hit_rate=0.0,
                    )
                )
                continue
            stats = _aggregate_records(bucket)
            bins = _calibration_bins_from_records(bucket)
            cal_error = _calibration_error(bins)
            quality = classify_forecast_quality(
                verified_count=len(bucket),
                mean_brier=stats["mean_brier"],
                calibration_error=cal_error,
                overconfidence_index=stats["overconfidence_index"],
                min_required=MIN_GROUP_FOR_QUALITY,
            )
            cells.append(
                MatrixCell(
                    origin_regime=regime,
                    horizon=horizon,
                    count=len(bucket),
                    group_quality=quality,
                    mean_brier=stats["mean_brier"],
                    mean_log_score=stats["mean_log_score"],
                    mean_boundary_brier=stats["mean_boundary_brier"],
                    top1_hit_rate=stats["top1_hit_rate"],
                )
            )

    regime_scores: list[RegimeScoreRow] = []
    for regime in regimes:
        bucket = [record for record in scoped if record.origin_regime == regime]
        if not bucket:
            continue
        stats = _aggregate_records(bucket)
        bins = _calibration_bins_from_records(bucket)
        cal_error = _calibration_error(bins)
        quality = classify_forecast_quality(
            verified_count=len(bucket),
            mean_brier=stats["mean_brier"],
            calibration_error=cal_error,
            overconfidence_index=stats["overconfidence_index"],
            min_required=MIN_GROUP_FOR_QUALITY,
        )
        regime_scores.append(
            RegimeScoreRow(
                origin_regime=regime,
                count=len(bucket),
                mean_brier=stats["mean_brier"],
                mean_log_score=stats["mean_log_score"],
                mean_boundary_brier=stats["mean_boundary_brier"],
                group_quality=quality,
                reliability_score=stats["top1_hit_rate"],
            )
        )

    return ForecastVerificationMatrix(
        generation_id=_display_generation_id(scope_id or "unknown"),
        horizons=horizons,
        regimes=regimes,
        cells=cells,
        regime_scores=regime_scores,
    )


def format_forecast_verification_matrix(matrix: ForecastVerificationMatrix) -> str:
    """ASCII verification matrix panel for dashboard."""
    lines = [
        "=== Forecast Verification Matrix | Phase D.3.1 ===",
        f"  Generation: {matrix.generation_id}  (matrix scoped — not cross-gen pooled)",
        "  (read-only evidence — does not modify D.3 forecasts)",
        f"  cell labels require n>={MIN_GROUP_FOR_QUALITY} for CAL/OVER/UNDER",
        "",
    ]
    if not matrix.regimes:
        lines.append("  no verified forecasts yet — validation window open")
        return "\n".join(lines)

    header = " " * 12 + "".join(f"H{horizon:<9}" for horizon in matrix.horizons)
    lines.append(header.rstrip())
    cell_map = {(cell.origin_regime, cell.horizon): cell for cell in matrix.cells}
    for regime in matrix.regimes:
        row = f"{regime:<12}"
        for horizon in matrix.horizons:
            cell = cell_map.get((regime, horizon))
            label = _quality_abbrev(cell.group_quality) if cell else "UNVER"
            suffix = f"({cell.count})" if cell and cell.count else ""
            row += f"{label:<4}{suffix:<5}"
        lines.append(row.rstrip())

    if matrix.regime_scores:
        lines.extend(["", "  Scores by origin_regime (↓ lower is better):"])
        lines.append(f"  {'':4}{'Brier':<10}{'Log':<10}{'BndBrier':<10}{'n':<5}{'quality'}")
        for row in matrix.regime_scores:
            lines.append(
                f"  {row.origin_regime:<4}"
                f"{row.mean_brier:<10.3f}"
                f"{row.mean_log_score:<10.3f}"
                f"{row.mean_boundary_brier:<10.3f}"
                f"{row.count:<5}"
                f"{row.group_quality}"
            )

        lines.extend(["", "  Calibration (top1 reliability):"])
        for row in matrix.regime_scores:
            filled = int(round(row.reliability_score * 10))
            bar = "█" * filled + "░" * (10 - filled)
            lines.append(f"  {row.origin_regime:<4} {bar}  {row.group_quality}")

    return "\n".join(lines)


def build_forecast_verification_report(
    store: ForecastVerificationStore | None = None,
    *,
    events: list[ManifoldEvent] | None = None,
) -> ForecastVerificationReport:
    store = store or ForecastVerificationStore()
    if events is not None:
        verify_pending_forecasts(events, store, persist=True)

    records = store.verified
    verified_count = len(records)
    pending_count = len(store.pending)
    window = ValidationWindow(
        verified_count=verified_count,
        pending_count=pending_count,
        min_required_for_global_quality=MIN_VERIFIED_FOR_QUALITY,
        min_required_for_group_quality=MIN_GROUP_FOR_QUALITY,
        window_open=verified_count < MIN_VERIFIED_FOR_QUALITY,
    )

    if verified_count == 0:
        return ForecastVerificationReport(
            version=VERIFICATION_VERSION,
            forecast_quality="UNVERIFIED",
            verified_count=0,
            pending_count=pending_count,
            mean_brier=0.0,
            mean_log_score=0.0,
            top1_hit_rate=0.0,
            top3_hit_rate=0.0,
            mean_boundary_brier=0.0,
            calibration_error=1.0,
            overconfidence_index=0.0,
            calibration_bins=[],
            recent_records=[],
            lineage=_empty_lineage(),
            matrix=_empty_matrix(),
            generation_scope=_empty_generation_scope(),
            validation_window=window,
        )

    scope = _resolve_generation_scope(records)
    scoped_records = _records_for_generation(records, scope.active_generation_id)

    stats = _aggregate_records(scoped_records)
    bins = _calibration_bins_from_records(scoped_records)
    cal_error = _calibration_error(bins)
    quality: ForecastQuality
    if scope.cross_generation_aggregate_blocked:
        quality = "UNVERIFIED"
    else:
        quality = classify_forecast_quality(
            verified_count=len(scoped_records),
            mean_brier=stats["mean_brier"],
            calibration_error=cal_error,
            overconfidence_index=stats["overconfidence_index"],
        )
    lineage = build_lineage_report(records)
    matrix = build_forecast_verification_matrix(records, generation_id=scope.active_generation_id)

    return ForecastVerificationReport(
        version=VERIFICATION_VERSION,
        forecast_quality=quality,
        verified_count=verified_count,
        pending_count=pending_count,
        mean_brier=stats["mean_brier"],
        mean_log_score=stats["mean_log_score"],
        top1_hit_rate=stats["top1_hit_rate"],
        top3_hit_rate=stats["top3_hit_rate"],
        mean_boundary_brier=stats["mean_boundary_brier"],
        calibration_error=cal_error,
        overconfidence_index=stats["overconfidence_index"],
        calibration_bins=bins,
        recent_records=records[-10:],
        lineage=lineage,
        matrix=matrix,
        generation_scope=scope,
        validation_window=window,
    )


def format_lineage_group(item: LineageGroupSummary) -> str:
    return (
        f"    {item.group_type}={item.group_key} n={item.count} "
        f"Brier={item.mean_brier:.3f} boundary_Brier={item.mean_boundary_brier:.3f} "
        f"quality={item.group_quality}"
    )


def format_forecast_verification_report(report: ForecastVerificationReport) -> str:
    lines = [
        f"=== Forecast Verification | Phase D.3.1 {report.version} ===",
        f"  global_quality={report.forecast_quality} verified={report.verified_count} "
        f"pending={report.pending_count}",
        f"  validation_window={'OPEN' if report.validation_window.window_open else 'SUFFICIENT'} "
        f"(need>={report.validation_window.min_required_for_global_quality})",
        f"  read_only_downstream={report.read_only_downstream}",
    ]
    scope = report.generation_scope
    if scope.multi_generation_detected:
        lines.append(
            f"  generation_scope={_display_generation_id(scope.active_generation_id)} "
            f"({scope.generation_count} frames, pooled_metrics=blocked={scope.cross_generation_aggregate_blocked})"
        )
    if report.verified_count == 0:
        lines.append("  no verified forecasts yet — collect evidence via validation window")
        return "\n".join(lines)

    lines.extend(
        [
            f"  scoped Brier={report.mean_brier:.4f} boundary_Brier={report.mean_boundary_brier:.4f} "
            f"(generation={_display_generation_id(scope.active_generation_id)})",
            f"  top1={report.top1_hit_rate:.2f} overconfidence={report.overconfidence_index:+.4f}",
        ]
    )

    if report.lineage.by_origin_regime:
        lines.append("")
        lines.append("  By origin_regime:")
        for item in report.lineage.by_origin_regime:
            lines.append(format_lineage_group(item))

    if report.lineage.by_horizon:
        lines.append("")
        lines.append("  By horizon:")
        for item in report.lineage.by_horizon:
            lines.append(format_lineage_group(item))

    if report.lineage.boundary_by_origin_regime:
        lines.append("")
        lines.append("  Boundary forecast by origin_regime:")
        for item in report.lineage.boundary_by_origin_regime:
            lines.append(
                f"    origin={item.group_key} n={item.count} "
                f"boundary_Brier={item.mean_boundary_brier:.3f} quality={item.group_quality}"
            )

    if report.lineage.by_forecast_status:
        lines.append("")
        lines.append("  By forecast_status:")
        for item in report.lineage.by_forecast_status:
            lines.append(format_lineage_group(item))

    lines.append("")
    lines.append(format_forecast_verification_matrix(report.matrix))
    return "\n".join(lines)


def run_forecast_with_verification(
    report: RegimeForecastReport,
    *,
    events: list[ManifoldEvent] | None = None,
    forecast_origin: str = "ci",
    record_forecast: bool = False,
    store: ForecastVerificationStore | None = None,
) -> ForecastVerificationReport:
    """Verify pending, optionally record new forecast. Quality is output-only."""
    events = events or extract_event_stream()
    store = store or ForecastVerificationStore()
    origin_ts = events[-1].timestamp if events else datetime.now(timezone.utc).isoformat()
    verify_pending_forecasts(events, store, persist=True)
    if record_forecast:
        store.record_forecast(
            report=report,
            forecast_origin=forecast_origin,
            origin_timestamp=origin_ts,
            persist=True,
        )
    return build_forecast_verification_report(store=store, events=None)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Forecast verification — Phase D.3.1")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--lineage", action="store_true", help="Show grouped lineage breakdown")
    parser.add_argument("--matrix", action="store_true", help="Show regime×horizon verification matrix")
    args = parser.parse_args(argv)

    events = extract_event_stream()
    report = build_forecast_verification_report(events=events)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    elif args.matrix:
        print(format_forecast_verification_matrix(report.matrix))
    else:
        print(format_forecast_verification_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
