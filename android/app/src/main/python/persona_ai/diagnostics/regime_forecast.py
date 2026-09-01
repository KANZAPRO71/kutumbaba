"""Phase D.3 — probabilistic regime forecast with explicit uncertainty.

Diagnostic-only: produces forecast + probability + uncertainty + warning.
Does NOT modify elasticity, arbitration, learning, or CI gate.

Pipeline:
  frozen generation → validated P → current regime → P^k → distribution
  → P(boundary within N) → calibrated confidence
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from persona_ai.diagnostics.arbitration_telemetry import ArbitrationTelemetryStore
from persona_ai.diagnostics.manifold_dynamics import (
    ALL_REGIMES,
    LAPLACE_ALPHA,
    MIN_EVENTS_FOR_MATRIX,
    TransitionMatrix,
    build_transition_matrix,
    extract_event_stream,
)
from persona_ai.diagnostics.markov_validation import (
    MarkovValidationReport,
    build_markov_validation_report,
)
from persona_ai.diagnostics.metastability import (
    MetastabilityReport,
    build_metastability_report,
)
from persona_ai.diagnostics.runtime_soft_observer import RuntimeSoftTelemetryStore

FORECAST_VERSION = "v1.1"
DEFAULT_HORIZON = 5
BOUNDARY_REGIMES = frozenset({"I5", "I6"})
CASCADE_MIDDLE = "I4"
CASCADE_SINK = "I5"
Z_NORMAL = 1.96
EPS = 1e-12

ConfidenceBand = Literal["LOW", "MEDIUM", "HIGH"]
ForecastStatus = Literal["CLEAR", "MONITOR", "CAUTION", "WITHHOLD"]
ForecastQuality = Literal["UNVERIFIED", "CALIBRATED", "OVERCONFIDENT", "UNDERCONFIDENT"]


def _regime_index() -> dict[str, int]:
    return {regime: index for index, regime in enumerate(ALL_REGIMES)}


def _dense_matrix(probabilities: dict[str, dict[str, float]]) -> list[list[float]]:
    return [[probabilities[source].get(target, 0.0) for target in ALL_REGIMES] for source in ALL_REGIMES]


def _vector_matrix_multiply(vector: list[float], matrix: list[list[float]]) -> list[float]:
    n = len(vector)
    return [sum(vector[row] * matrix[row][col] for row in range(n)) for col in range(n)]


def _matrix_power(matrix: list[list[float]], exponent: int) -> list[list[float]]:
    n = len(matrix)
    if exponent <= 0:
        return [[1.0 if row == col else 0.0 for col in range(n)] for row in range(n)]
    result = [row[:] for row in matrix]
    base = [row[:] for row in matrix]
    power = exponent - 1
    while power > 0:
        if power % 2 == 1:
            result = _matrix_multiply(result, base)
        base = _matrix_multiply(base, base)
        power //= 2
    return result


def _matrix_multiply(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    n = len(a)
    return [
        [sum(a[row][k] * b[k][col] for k in range(n)) for col in range(n)]
        for row in range(n)
    ]


def _one_hot(regime: str) -> list[float]:
    vector = [0.0] * len(ALL_REGIMES)
    if regime in _regime_index():
        vector[_regime_index()[regime]] = 1.0
    return vector


def _distribution_dict(vector: list[float]) -> dict[str, float]:
    return {ALL_REGIMES[index]: round(vector[index], 6) for index in range(len(ALL_REGIMES))}


@dataclass
class TransitionUncertainty:
    effective_sample_size: float
    row_sample_sizes: dict[str, float]
    confidence_interval_95: dict[str, dict[str, tuple[float, float]]]
    max_interval_width: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_sample_size": self.effective_sample_size,
            "row_sample_sizes": self.row_sample_sizes,
            "confidence_interval_95": {
                source: {target: list(bounds) for target, bounds in row.items()}
                for source, row in self.confidence_interval_95.items()
            },
            "max_interval_width": self.max_interval_width,
        }


def estimate_transition_uncertainty(matrix: TransitionMatrix) -> TransitionUncertainty:
    """Wilson-style normal CI from multinomial row counts (post-Laplace de-bias)."""
    row_sizes: dict[str, float] = {}
    intervals: dict[str, dict[str, tuple[float, float]]] = {}
    max_width = 0.0
    total_transitions = float(matrix.sample_transitions)

    for source in ALL_REGIMES:
        row = matrix.counts.get(source, {})
        row_total = sum(row.values()) - len(ALL_REGIMES) * LAPLACE_ALPHA
        row_total = max(row_total, 0.0)
        row_sizes[source] = round(row_total, 4)
        intervals[source] = {}
        if row_total <= 0:
            continue
        for target in ALL_REGIMES:
            count = max(row.get(target, 0.0) - LAPLACE_ALPHA, 0.0)
            probability = count / row_total if row_total else 0.0
            stderr = math.sqrt(max(probability * (1.0 - probability) / row_total, EPS))
            lower = max(0.0, probability - Z_NORMAL * stderr)
            upper = min(1.0, probability + Z_NORMAL * stderr)
            intervals[source][target] = (round(lower, 6), round(upper, 6))
            max_width = max(max_width, upper - lower)

    return TransitionUncertainty(
        effective_sample_size=round(total_transitions, 4),
        row_sample_sizes=row_sizes,
        confidence_interval_95=intervals,
        max_interval_width=round(max_width, 6),
    )


@dataclass
class HorizonForecast:
    horizon: int
    probabilities: dict[str, float]
    p_boundary_exact: float
    p_boundary_within: float
    p_cascade_i4_i5: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _first_passage_boundary(
    matrix: list[list[float]],
    start_regime: str,
    *,
    max_horizon: int,
) -> tuple[dict[int, float], float]:
    """P(boundary at step t) and P(boundary within N) via non-boundary survival."""
    index = _regime_index()
    boundary_indices = [index[regime] for regime in BOUNDARY_REGIMES if regime in index]
    dist = _one_hot(start_regime)
    cumulative = 0.0
    per_step: dict[int, float] = {}

    for step in range(1, max_horizon + 1):
        hit = 0.0
        for source_index, source_regime in enumerate(ALL_REGIMES):
            if source_regime in BOUNDARY_REGIMES:
                continue
            for boundary_index in boundary_indices:
                hit += dist[source_index] * matrix[source_index][boundary_index]
        per_step[step] = round(hit, 6)
        cumulative += hit
        dist = _vector_matrix_multiply(dist, matrix)
        for boundary_index in boundary_indices:
            dist[boundary_index] = 0.0
        total = sum(dist)
        if total > 0:
            dist = [value / total for value in dist]

    return per_step, round(min(cumulative, 1.0), 6)


def _cascade_probability(
    matrix: list[list[float]],
    start_regime: str,
    *,
    horizon: int,
) -> float:
    """P(I4 then I5 within horizon) — I4 at t, I5 at t+1 for some t < horizon."""
    index = _regime_index()
    i4 = index.get(CASCADE_MIDDLE)
    i5 = index.get(CASCADE_SINK)
    if i4 is None or i5 is None:
        return 0.0

    dist = _one_hot(start_regime)
    cascade = 0.0
    for step in range(1, horizon):
        dist = _vector_matrix_multiply(dist, matrix)
        mass_i4 = dist[i4]
        cascade += mass_i4 * matrix[i4][i5]
    return round(min(cascade, 1.0), 6)


def forecast_regime_distribution(
    matrix: TransitionMatrix,
    *,
    current_regime: str,
    horizon: int = DEFAULT_HORIZON,
) -> HorizonForecast:
    """D.3.1 — π₀ P^h regime distribution at horizon h."""
    dense = _dense_matrix(matrix.probabilities)
    powered = _matrix_power(dense, horizon)
    distribution = _vector_matrix_multiply(_one_hot(current_regime), powered)
    per_step, within = _first_passage_boundary(dense, current_regime, max_horizon=horizon)
    exact = per_step.get(1, 0.0)
    cascade = _cascade_probability(dense, current_regime, horizon=horizon)
    return HorizonForecast(
        horizon=horizon,
        probabilities=_distribution_dict(distribution),
        p_boundary_exact=exact,
        p_boundary_within=within,
        p_cascade_i4_i5=cascade,
    )


@dataclass
class BoundaryHorizonProfile:
    horizons: list[int]
    p_boundary_within: dict[int, float]
    p_boundary_exact: dict[int, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_boundary_horizon_profile(
    matrix: TransitionMatrix,
    *,
    current_regime: str,
    horizons: list[int] | None = None,
) -> BoundaryHorizonProfile:
    """D.3.2 — P(τ_boundary ≤ N) for multiple N."""
    dense = _dense_matrix(matrix.probabilities)
    horizons = horizons or [1, 5, 10]
    max_h = max(horizons)
    per_step, _ = _first_passage_boundary(dense, current_regime, max_horizon=max_h)
    cumulative = 0.0
    within: dict[int, float] = {}
    exact: dict[int, float] = {}
    for step in range(1, max_h + 1):
        cumulative += per_step.get(step, 0.0)
        if step in horizons:
            within[step] = round(min(cumulative, 1.0), 6)
            exact[step] = per_step.get(step, 0.0)
    return BoundaryHorizonProfile(
        horizons=horizons,
        p_boundary_within=within,
        p_boundary_exact=exact,
    )


@dataclass
class ForecastValidity:
    generation_id: str | None
    markov_order_valid: bool
    kernel_stable: bool
    lossy_observation: bool
    sufficient_samples: bool
    structural_shift: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalibratedConfidence:
    confidence_band: ConfidenceBand
    forecast_status: ForecastStatus
    downgrade_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def calibrate_forecast_confidence(
    *,
    validity: ForecastValidity,
    uncertainty: TransitionUncertainty,
    validation: MarkovValidationReport | None,
    metastability: MetastabilityReport | None,
    p_boundary_within: float,
) -> CalibratedConfidence:
    """D.3.3 — downgrade confidence when kernel or observation is unreliable."""
    reasons: list[str] = []
    band: ConfidenceBand = "HIGH"
    status: ForecastStatus = "CLEAR"

    if not validity.sufficient_samples:
        return CalibratedConfidence("LOW", "WITHHOLD", ["insufficient_transition_samples"])

    if not validity.markov_order_valid:
        reasons.append("markov_order_violated")
        band = "LOW"
    if not validity.kernel_stable or validity.structural_shift:
        reasons.append("kernel_non_stationary")
        band = "LOW"
    if validity.lossy_observation:
        reasons.append("lossy_observation_operator")
        if band == "HIGH":
            band = "MEDIUM"
    if uncertainty.effective_sample_size < MIN_EVENTS_FOR_MATRIX * 2:
        reasons.append("low_effective_sample_size")
        band = "LOW"
    if uncertainty.max_interval_width > 0.35:
        reasons.append("wide_transition_ci")
        if band == "HIGH":
            band = "MEDIUM"
        else:
            band = "LOW"

    if metastability and metastability.sufficient_samples:
        if metastability.spectral_gap.gap_collapsing:
            reasons.append("spectral_gap_collapse")
            band = "LOW"
        if metastability.boundary_warning.warning_active:
            reasons.append("metastability_boundary_warning")

    if p_boundary_within >= 0.25:
        status = "CAUTION"
    elif p_boundary_within >= 0.10:
        status = "MONITOR"
    else:
        status = "CLEAR"

    if band == "LOW":
        if status == "CLEAR":
            status = "MONITOR"
        if validity.structural_shift or not validity.markov_order_valid:
            status = "WITHHOLD"

    if validation and validation.stationarity.classification == "structural_kernel_shift":
        reasons.append("structural_kernel_shift")
        band = "LOW"
        status = "WITHHOLD"

    return CalibratedConfidence(
        confidence_band=band,
        forecast_status=status,
        downgrade_reasons=sorted(set(reasons)),
    )


@dataclass
class RegimeForecastReport:
    version: str
    current_regime: str
    forecast: HorizonForecast
    boundary_profile: BoundaryHorizonProfile
    uncertainty: TransitionUncertainty
    validity: ForecastValidity
    confidence: CalibratedConfidence
    forecast_quality: ForecastQuality = "UNVERIFIED"
    verification: dict[str, Any] | None = None
    diagnostics_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "forecast_version": self.version,
            "current_regime": self.current_regime,
            "forecast": self.forecast.to_dict(),
            "boundary_profile": self.boundary_profile.to_dict(),
            "uncertainty": self.uncertainty.to_dict(),
            "validity": self.validity.to_dict(),
            "confidence": self.confidence.to_dict(),
            "forecast_quality": self.forecast_quality,
            "diagnostics_only": self.diagnostics_only,
        }
        if self.verification is not None:
            payload["verification"] = self.verification
        return payload


def _current_regime_from_events(events: list) -> str:
    if not events:
        return "I0"
    for event in reversed(events):
        if event.invariant_class in ALL_REGIMES:
            return event.invariant_class
    return "I0"


def build_regime_forecast_report(
    *,
    ci_store: ArbitrationTelemetryStore | None = None,
    runtime_store: RuntimeSoftTelemetryStore | None = None,
    horizon: int = DEFAULT_HORIZON,
    validation_report: MarkovValidationReport | None = None,
    metastability_report: MetastabilityReport | None = None,
    record_forecast: bool = False,
    forecast_origin: str = "runtime",
) -> RegimeForecastReport:
    from persona_ai.diagnostics.forecast_verification import (
        build_forecast_verification_report,
        run_forecast_with_verification,
    )

    events = extract_event_stream(ci_store=ci_store, runtime_store=runtime_store)
    current_regime = _current_regime_from_events(events)
    matrix = build_transition_matrix(events)
    validation = validation_report or build_markov_validation_report(
        ci_store=ci_store,
        runtime_store=runtime_store,
        update_baseline=False,
    )
    metastability = metastability_report or build_metastability_report(
        ci_store=ci_store,
        runtime_store=runtime_store,
        update_baseline=False,
    )

    lossy = any(event.lossy for event in events[-5:]) if events else True
    generation_id = matrix.generation_id if matrix else validation.generation_id

    empty_forecast = HorizonForecast(horizon, {regime: 0.0 for regime in ALL_REGIMES}, 0.0, 0.0, 0.0)
    empty_profile = BoundaryHorizonProfile([1, 5, 10], {}, {})
    empty_uncertainty = TransitionUncertainty(0.0, {}, {}, 1.0)

    validity = ForecastValidity(
        generation_id=generation_id,
        markov_order_valid=validation.markov_order.order1_valid,
        kernel_stable=validation.stationarity.kernel_stable,
        lossy_observation=lossy,
        sufficient_samples=matrix is not None and matrix.sample_transitions >= MIN_EVENTS_FOR_MATRIX,
        structural_shift=validation.stationarity.classification == "structural_kernel_shift",
    )

    if matrix is None:
        confidence = calibrate_forecast_confidence(
            validity=validity,
            uncertainty=empty_uncertainty,
            validation=validation,
            metastability=metastability,
            p_boundary_within=0.0,
        )
        verification = build_forecast_verification_report(events=events)
        return RegimeForecastReport(
            version=FORECAST_VERSION,
            current_regime=current_regime,
            forecast=empty_forecast,
            boundary_profile=empty_profile,
            uncertainty=empty_uncertainty,
            validity=validity,
            confidence=confidence,
            forecast_quality=verification.forecast_quality,
            verification=verification.to_dict(),
        )

    uncertainty = estimate_transition_uncertainty(matrix)
    forecast = forecast_regime_distribution(matrix, current_regime=current_regime, horizon=horizon)
    profile = compute_boundary_horizon_profile(
        matrix,
        current_regime=current_regime,
        horizons=[1, horizon, max(horizon * 2, 10)],
    )
    confidence = calibrate_forecast_confidence(
        validity=validity,
        uncertainty=uncertainty,
        validation=validation,
        metastability=metastability,
        p_boundary_within=forecast.p_boundary_within,
    )

    report = RegimeForecastReport(
        version=FORECAST_VERSION,
        current_regime=current_regime,
        forecast=forecast,
        boundary_profile=profile,
        uncertainty=uncertainty,
        validity=validity,
        confidence=confidence,
    )
    verification = run_forecast_with_verification(
        report,
        events=events,
        forecast_origin=forecast_origin,
        record_forecast=record_forecast,
    )
    report.forecast_quality = verification.forecast_quality
    report.verification = verification.to_dict()
    # forecast_quality is OUTPUT-ONLY — never feed back into calibrate_forecast_confidence.
    return report


def format_regime_forecast_report(report: RegimeForecastReport) -> str:
    lines = [
        f"=== Regime Forecast | Phase D.3 {report.version} ===",
        f"  current={report.current_regime} gen={report.validity.generation_id or 'n/a'}",
        f"  forecast_status={report.confidence.forecast_status} "
        f"confidence={report.confidence.confidence_band} "
        f"forecast_quality={report.forecast_quality}",
    ]
    if report.confidence.downgrade_reasons:
        lines.append(f"  downgrade: {', '.join(report.confidence.downgrade_reasons)}")

    if not report.validity.sufficient_samples:
        lines.append("  insufficient samples — forecast withheld")
        return "\n".join(lines)

    forecast = report.forecast
    lines.extend(
        [
            "",
            f"  Forecast horizon: {forecast.horizon} events",
        ]
    )
    for regime in ALL_REGIMES:
        probability = forecast.probabilities.get(regime, 0.0)
        if probability >= 0.01:
            lines.append(f"    {regime}  {probability:.2f}")

    lines.extend(
        [
            "",
            f"  P(I5|I6 exact next) = {forecast.p_boundary_exact:.2f}",
            f"  P(boundary within {forecast.horizon}) = {forecast.p_boundary_within:.2f}",
            f"  P(I4→I5 cascade ≤{forecast.horizon}) = {forecast.p_cascade_i4_i5:.2f}",
        ]
    )

    if report.boundary_profile.p_boundary_within:
        lines.append("")
        lines.append("  Boundary within N:")
        for step, probability in sorted(report.boundary_profile.p_boundary_within.items()):
            exact = report.boundary_profile.p_boundary_exact.get(step, 0.0)
            lines.append(f"    N={step}: within={probability:.2f} exact={exact:.2f}")

    uncertainty = report.uncertainty
    lines.extend(
        [
            "",
            f"  uncertainty: ESS={uncertainty.effective_sample_size:.0f} "
            f"max_CI_width={uncertainty.max_interval_width:.3f}",
            f"  validity: order_ok={report.validity.markov_order_valid} "
            f"stable={report.validity.kernel_stable} lossy={report.validity.lossy_observation}",
        ]
    )
    if report.verification and report.verification.get("verified_count", 0) > 0:
        lines.extend(
            [
                "",
                f"  verification: Brier={report.verification.get('mean_brier', 0):.4f} "
                f"top1={report.verification.get('top1_hit_rate', 0):.2f} "
                f"cal_err={report.verification.get('calibration_error', 0):.4f}",
            ]
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Probabilistic regime forecast — Phase D.3")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    args = parser.parse_args(argv)

    report = build_regime_forecast_report(horizon=args.horizon)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_regime_forecast_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
