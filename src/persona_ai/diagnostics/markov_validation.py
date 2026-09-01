"""Phase D.1 — statistical physics validation of Markov regime dynamics.

Requires frozen inertial frames (Phase D hardening). Validates whether the
observed dynamical law is stable under lossy observation — not merely whether
labels changed.

Components:
  1. Markov order stability (order-1 vs order-2 likelihood-ratio / χ²)
  2. Cross-commit kernel stationarity (homogeneity test on transition matrices)
  3. KL divergence rate (current commit vs frozen baseline kernel)
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from persona_ai.diagnostics.arbitration_telemetry import ArbitrationTelemetryStore
from persona_ai.diagnostics.manifold_dynamics import (
    ALL_REGIMES,
    MIN_EVENTS_FOR_MATRIX,
    ManifoldEvent,
    TransitionMatrix,
    build_transition_matrix,
    extract_event_stream,
)
from persona_ai.diagnostics.runtime_soft_observer import RuntimeSoftTelemetryStore

VALIDATION_VERSION = "v1"
DEFAULT_BASELINE_PATH = Path(".persona_ai/markov_baseline.json")
MIN_ORDER_TEST_EVENTS = 4
MIN_CONTEXT_COUNT = 2
EPS = 1e-12


def _chi2_pvalue(statistic: float, df: int) -> float:
    """Upper-tail p-value for χ²(df) without scipy."""
    if statistic <= 0 or df <= 0:
        return 1.0
    return _gammaincc(df * 0.5, statistic * 0.5)


def _gammaincc(a: float, x: float) -> float:
    if x <= 0 or a <= 0:
        return 1.0
    if x < a + 1.0:
        return 1.0 - _gammainc_series(a, x)
    return _gammainc_continued_fraction(a, x)


def _gammainc_series(a: float, x: float) -> float:
    ap = a
    summ = 1.0 / a
    delta = summ
    for _ in range(200):
        ap += 1.0
        delta *= x / ap
        summ += delta
        if abs(delta) < abs(summ) * 1e-10:
            break
    return summ * math.exp(-x + a * math.log(x) - math.lgamma(a))


def _gammainc_continued_fraction(a: float, x: float) -> float:
    b = x + 1.0 - a
    c = 1.0 / EPS
    d = 1.0 / b
    h = d
    for index in range(1, 200):
        an = -index * (index - a)
        b += 2.0
        d = an * d + b
        if abs(d) < EPS:
            d = EPS
        c = b + an / c
        if abs(c) < EPS:
            c = EPS
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-10:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def _filter_generation(events: list[ManifoldEvent], generation_id: str | None) -> list[ManifoldEvent]:
    if not generation_id:
        return [event for event in events if event.generation_id]
    return [event for event in events if event.generation_id == generation_id]


def _bigram_counts(events: list[ManifoldEvent]) -> dict[tuple[str, str], float]:
    counts: dict[tuple[str, str], float] = {}
    for prev, curr in zip(events, events[1:]):
        if prev.generation_id != curr.generation_id:
            continue
        key = (prev.invariant_class, curr.invariant_class)
        counts[key] = counts.get(key, 0.0) + 1.0
    return counts


def _trigram_counts(events: list[ManifoldEvent]) -> dict[tuple[str, str, str], float]:
    counts: dict[tuple[str, str, str], float] = {}
    for first, middle, last in zip(events, events[1:], events[2:]):
        if not (first.generation_id == middle.generation_id == last.generation_id):
            continue
        key = (first.invariant_class, middle.invariant_class, last.invariant_class)
        counts[key] = counts.get(key, 0.0) + 1.0
    return counts


def _outgoing_from_state(bigrams: dict[tuple[str, str], float], state: str) -> dict[str, float]:
    row = {target: 0.0 for target in ALL_REGIMES}
    for (source, target), count in bigrams.items():
        if source == state:
            row[target] += count
    return row


def split_events_by_ci_commit(events: list[ManifoldEvent]) -> list[tuple[str, list[ManifoldEvent]]]:
    """Partition event stream by CI lattice anchors (commit blocks)."""
    blocks: list[tuple[str, list[ManifoldEvent]]] = []
    current_commit = "genesis"
    current_events: list[ManifoldEvent] = []
    for event in events:
        if event.event_kind == "ci_lattice":
            if current_events:
                blocks.append((current_commit, current_events))
            current_commit = event.snapshot_id
            current_events = [event]
        else:
            current_events.append(event)
    if current_events:
        blocks.append((current_commit, current_events))
    return blocks


@dataclass
class MarkovOrderReport:
    sufficient_samples: bool
    order1_valid: bool
    markov_order_score: float
    delta_log_likelihood: float
    chi_square_statistic: float
    chi_square_p_value: float
    hidden_memory_detected: bool
    triple_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_markov_order(
    events: list[ManifoldEvent],
    *,
    generation_id: str | None = None,
) -> MarkovOrderReport:
    """H0: P(I_{t+1}|I_t) sufficient vs H1: P(I_{t+1}|I_t,I_{t-1}) improves fit."""
    filtered = _filter_generation(events, generation_id)
    if len(filtered) < MIN_ORDER_TEST_EVENTS:
        return MarkovOrderReport(
            sufficient_samples=False,
            order1_valid=True,
            markov_order_score=0.0,
            delta_log_likelihood=0.0,
            chi_square_statistic=0.0,
            chi_square_p_value=1.0,
            hidden_memory_detected=False,
            triple_count=0,
        )

    bigrams = _bigram_counts(filtered)
    trigrams = _trigram_counts(filtered)
    if not trigrams:
        return MarkovOrderReport(
            sufficient_samples=False,
            order1_valid=True,
            markov_order_score=0.0,
            delta_log_likelihood=0.0,
            chi_square_statistic=0.0,
            chi_square_p_value=1.0,
            hidden_memory_detected=False,
            triple_count=0,
        )

    log_l1 = 0.0
    log_l2 = 0.0
    chi_square = 0.0
    df = 0

    for (source, middle, target), count in trigrams.items():
        n_ijk = count
        n_ij = bigrams.get((source, middle), 0.0)
        if n_ij <= 0:
            continue

        middle_out = _outgoing_from_state(bigrams, middle)
        n_j_dot = sum(middle_out.values())
        n_jk = middle_out.get(target, 0.0)
        if n_j_dot <= 0:
            continue

        p1 = max(n_jk / n_j_dot, EPS)
        p2 = max(n_ijk / n_ij, EPS)
        log_l1 += n_ijk * math.log(p1)
        log_l2 += n_ijk * math.log(p2)

        expected = n_ij * p1
        if expected >= MIN_CONTEXT_COUNT:
            chi_square += (n_ijk - expected) ** 2 / expected
            df += 1

    delta_ll = log_l2 - log_l1
    lr_statistic = max(0.0, 2.0 * delta_ll)
    statistic = max(lr_statistic, chi_square)
    df = max(1, df - len({middle for _, middle, _ in trigrams}))
    p_value = _chi2_pvalue(statistic, df)
    hidden_memory = p_value < 0.05
    order_score = round(1.0 - p_value, 6)

    return MarkovOrderReport(
        sufficient_samples=True,
        order1_valid=not hidden_memory,
        markov_order_score=order_score,
        delta_log_likelihood=round(delta_ll, 6),
        chi_square_statistic=round(statistic, 6),
        chi_square_p_value=round(p_value, 6),
        hidden_memory_detected=hidden_memory,
        triple_count=len(trigrams),
    )


@dataclass
class StationarityReport:
    sufficient_samples: bool
    kernel_stable: bool
    stationarity_p_value: float
    transition_matrix_divergence: float
    regime_distribution_shift: float
    baseline_commit_id: str | None
    current_commit_id: str | None
    classification: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _regime_marginal(events: list[ManifoldEvent]) -> dict[str, float]:
    counts = {regime: 0.0 for regime in ALL_REGIMES}
    for event in events:
        if event.invariant_class in counts:
            counts[event.invariant_class] += 1.0
    total = sum(counts.values()) or 1.0
    return {regime: counts[regime] / total for regime in ALL_REGIMES}


def _distribution_l1(a: dict[str, float], b: dict[str, float]) -> float:
    return round(sum(abs(a.get(regime, 0.0) - b.get(regime, 0.0)) for regime in ALL_REGIMES), 6)


def _matrix_max_divergence(
    matrix_a: dict[str, dict[str, float]],
    matrix_b: dict[str, dict[str, float]],
) -> float:
    divergence = 0.0
    for source in ALL_REGIMES:
        for target in ALL_REGIMES:
            divergence = max(
                divergence,
                abs(matrix_a.get(source, {}).get(target, 0.0) - matrix_b.get(source, {}).get(target, 0.0)),
            )
    return round(divergence, 6)


def evaluate_kernel_stationarity(
    baseline_events: list[ManifoldEvent],
    current_events: list[ManifoldEvent],
    *,
    generation_id: str | None = None,
    baseline_commit_id: str | None = None,
    current_commit_id: str | None = None,
) -> StationarityReport:
    """χ² homogeneity on transition rows between CI commit blocks."""
    matrix_a = build_transition_matrix(baseline_events, generation_id=generation_id)
    matrix_b = build_transition_matrix(current_events, generation_id=generation_id)
    if matrix_a is None or matrix_b is None:
        return StationarityReport(
            sufficient_samples=False,
            kernel_stable=True,
            stationarity_p_value=1.0,
            transition_matrix_divergence=0.0,
            regime_distribution_shift=0.0,
            baseline_commit_id=baseline_commit_id,
            current_commit_id=current_commit_id,
            classification="insufficient_samples",
        )

    chi_square = 0.0
    df = 0
    for source in ALL_REGIMES:
        row_a = matrix_a.counts.get(source, {})
        row_b = matrix_b.counts.get(source, {})
        n_a = sum(row_a.values()) - len(ALL_REGIMES)
        n_b = sum(row_b.values()) - len(ALL_REGIMES)
        if n_a <= 0 and n_b <= 0:
            continue
        pooled = {target: row_a.get(target, 0.0) + row_b.get(target, 0.0) for target in ALL_REGIMES}
        pool_total = sum(pooled.values()) - 2 * len(ALL_REGIMES)
        if pool_total <= 0:
            continue
        for target in ALL_REGIMES:
            observed_a = max(row_a.get(target, 0.0) - 1.0, 0.0)
            observed_b = max(row_b.get(target, 0.0) - 1.0, 0.0)
            expected_a = n_a * (pooled[target] - 2.0) / pool_total if pool_total else 0.0
            expected_b = n_b * (pooled[target] - 2.0) / pool_total if pool_total else 0.0
            if expected_a >= MIN_CONTEXT_COUNT:
                chi_square += (observed_a - expected_a) ** 2 / expected_a
                df += 1
            if expected_b >= MIN_CONTEXT_COUNT:
                chi_square += (observed_b - expected_b) ** 2 / expected_b
                df += 1

    df = max(1, df - len(ALL_REGIMES))
    p_value = _chi2_pvalue(chi_square, df)
    divergence = _matrix_max_divergence(matrix_a.probabilities, matrix_b.probabilities)
    shift = _distribution_l1(_regime_marginal(baseline_events), _regime_marginal(current_events))

    if divergence < 0.05 and shift < 0.05:
        classification = "stable_regime_dynamics"
    elif divergence < 0.15:
        classification = "slow_calibration_drift"
    else:
        classification = "structural_kernel_shift"

    return StationarityReport(
        sufficient_samples=True,
        kernel_stable=p_value >= 0.05,
        stationarity_p_value=round(p_value, 6),
        transition_matrix_divergence=divergence,
        regime_distribution_shift=shift,
        baseline_commit_id=baseline_commit_id,
        current_commit_id=current_commit_id,
        classification=classification,
    )


@dataclass
class KLDivergenceReport:
    sufficient_samples: bool
    kl_global: float
    kl_per_regime: dict[str, float]
    entropy_production_rate: float
    baseline_commit_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _empirical_stationary(events: list[ManifoldEvent]) -> dict[str, float]:
    marginal = _regime_marginal(events)
    total = sum(marginal.values()) or 1.0
    return {regime: marginal[regime] / total for regime in ALL_REGIMES}


def compute_kl_divergence_rate(
    current: TransitionMatrix,
    baseline: TransitionMatrix,
    *,
    events: list[ManifoldEvent] | None = None,
    baseline_commit_id: str | None = None,
) -> KLDivergenceReport:
    """KL(current || baseline) = Σ_i π_i Σ_j P_ij log(P_ij / Q_ij)."""
    pi = _empirical_stationary(events or [])
    kl_global = 0.0
    kl_per_regime: dict[str, float] = {}
    entropy_prod = 0.0

    for source in ALL_REGIMES:
        row_kl = 0.0
        row_entropy = 0.0
        for target in ALL_REGIMES:
            p = current.probabilities.get(source, {}).get(target, EPS)
            q = baseline.probabilities.get(source, {}).get(target, EPS)
            if p > EPS:
                row_entropy -= pi.get(source, 0.0) * p * math.log(p)
            if p > EPS and q > EPS:
                row_kl += p * math.log(p / q)
        kl_per_regime[source] = round(row_kl, 6)
        kl_global += pi.get(source, 0.0) * row_kl
        entropy_prod += row_entropy

    return KLDivergenceReport(
        sufficient_samples=True,
        kl_global=round(kl_global, 6),
        kl_per_regime=kl_per_regime,
        entropy_production_rate=round(entropy_prod, 6),
        baseline_commit_id=baseline_commit_id,
    )


@dataclass
class MarkovBaselineStore:
    path: Path = field(default_factory=lambda: DEFAULT_BASELINE_PATH)
    commit_id: str | None = None
    generation_id: str | None = None
    transition_matrix: dict[str, dict[str, float]] | None = None

    def __post_init__(self) -> None:
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.commit_id = raw.get("commit_id")
        self.generation_id = raw.get("generation_id")
        self.transition_matrix = raw.get("transition_matrix")

    def save(
        self,
        *,
        commit_id: str,
        generation_id: str,
        matrix: TransitionMatrix,
    ) -> None:
        self.commit_id = commit_id
        self.generation_id = generation_id
        self.transition_matrix = matrix.probabilities
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "validation_version": VALIDATION_VERSION,
            "commit_id": commit_id,
            "generation_id": generation_id,
            "transition_matrix": matrix.probabilities,
            "sample_transitions": matrix.sample_transitions,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def as_transition_matrix(self, generation_id: str) -> TransitionMatrix | None:
        if not self.transition_matrix:
            return None
        counts = {
            source: {target: 1.0 for target in ALL_REGIMES} for source in ALL_REGIMES
        }
        return TransitionMatrix(
            generation_id=generation_id,
            counts=counts,
            probabilities=self.transition_matrix,
            energy={
                source: {
                    target: round(-math.log(max(prob, EPS)), 6)
                    for target, prob in row.items()
                }
                for source, row in self.transition_matrix.items()
            },
            sample_transitions=0,
        )


@dataclass
class MarkovValidationReport:
    version: str
    generation_id: str | None
    markov_order: MarkovOrderReport
    stationarity: StationarityReport
    kl_divergence: KLDivergenceReport
    commit_blocks: int
    diagnostics_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_version": self.version,
            "generation_id": self.generation_id,
            "markov_order": self.markov_order.to_dict(),
            "stationarity": self.stationarity.to_dict(),
            "kl_divergence": self.kl_divergence.to_dict(),
            "commit_blocks": self.commit_blocks,
            "diagnostics_only": self.diagnostics_only,
        }


def build_markov_validation_report(
    *,
    ci_store: ArbitrationTelemetryStore | None = None,
    runtime_store: RuntimeSoftTelemetryStore | None = None,
    baseline_store: MarkovBaselineStore | None = None,
    update_baseline: bool = False,
) -> MarkovValidationReport:
    events = extract_event_stream(ci_store=ci_store, runtime_store=runtime_store)
    generation_id = None
    if events:
        from collections import Counter

        generation_id = Counter(event.generation_id for event in events if event.generation_id).most_common(1)[0][0]

    order = evaluate_markov_order(events, generation_id=generation_id)
    blocks = split_events_by_ci_commit(events)

    stationarity = StationarityReport(
        sufficient_samples=False,
        kernel_stable=True,
        stationarity_p_value=1.0,
        transition_matrix_divergence=0.0,
        regime_distribution_shift=0.0,
        baseline_commit_id=None,
        current_commit_id=None,
        classification="insufficient_commit_blocks",
    )
    kl_report = KLDivergenceReport(
        sufficient_samples=False,
        kl_global=0.0,
        kl_per_regime={},
        entropy_production_rate=0.0,
        baseline_commit_id=None,
    )

    baseline = baseline_store or MarkovBaselineStore()
    current_matrix = build_transition_matrix(events, generation_id=generation_id)

    if len(blocks) >= 2:
        baseline_commit_id, baseline_events = blocks[-2]
        current_commit_id, current_events = blocks[-1]
        stationarity = evaluate_kernel_stationarity(
            baseline_events,
            current_events,
            generation_id=generation_id,
            baseline_commit_id=baseline_commit_id,
            current_commit_id=current_commit_id,
        )
    elif len(blocks) == 1:
        current_commit_id, _ = blocks[0]

    if current_matrix and baseline.transition_matrix and baseline.generation_id == generation_id:
        baseline_matrix = baseline.as_transition_matrix(generation_id)
        if baseline_matrix:
            kl_report = compute_kl_divergence_rate(
                current_matrix,
                baseline_matrix,
                events=events,
                baseline_commit_id=baseline.commit_id,
            )

    if update_baseline and current_matrix and blocks:
        baseline.save(
            commit_id=blocks[-1][0],
            generation_id=generation_id or "",
            matrix=current_matrix,
        )

    return MarkovValidationReport(
        version=VALIDATION_VERSION,
        generation_id=generation_id,
        markov_order=order,
        stationarity=stationarity,
        kl_divergence=kl_report,
        commit_blocks=len(blocks),
    )


def format_markov_validation_report(report: MarkovValidationReport) -> str:
    lines = [
        f"=== Markov Validation | Phase D.1 {report.version} ===",
        f"  generation={report.generation_id or 'n/a'} commits={report.commit_blocks}",
        "",
        "  MARKOV ORDER",
        f"    order1_valid={report.markov_order.order1_valid} "
        f"p={report.markov_order.chi_square_p_value:.4f} "
        f"ΔlogL={report.markov_order.delta_log_likelihood:.4f} "
        f"hidden_memory={report.markov_order.hidden_memory_detected}",
        "",
        "  STATIONARITY",
        f"    kernel_stable={report.stationarity.kernel_stable} "
        f"p={report.stationarity.stationarity_p_value:.4f} "
        f"ΔP_max={report.stationarity.transition_matrix_divergence:.4f} "
        f"regime_shift={report.stationarity.regime_distribution_shift:.4f}",
        f"    classification={report.stationarity.classification}",
        "",
        "  KL LANDSCAPE",
        f"    KL(current||baseline)={report.kl_divergence.kl_global:.6f} "
        f"entropy_rate={report.kl_divergence.entropy_production_rate:.4f}",
    ]
    if report.kl_divergence.kl_per_regime:
        top_kl = sorted(
            ((regime, value) for regime, value in report.kl_divergence.kl_per_regime.items() if value > 0),
            key=lambda item: -item[1],
        )[:4]
        if top_kl:
            formatted = " ".join(f"{regime}:{value:.4f}" for regime, value in top_kl)
            lines.append(f"    KL_per_regime: {formatted}")
    return "\n".join(lines)


def check_markov_validation_for_ci(
    *,
    ci_store: ArbitrationTelemetryStore | None = None,
    runtime_store: RuntimeSoftTelemetryStore | None = None,
    update_baseline: bool = True,
) -> dict[str, Any]:
    """Diagnostic-only CI hook — never gates promotion."""
    report = build_markov_validation_report(
        ci_store=ci_store,
        runtime_store=runtime_store,
        update_baseline=update_baseline,
    )
    return report.to_dict()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Markov validation — Phase D.1 statistical layer")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-update-baseline", action="store_true")
    args = parser.parse_args(argv)

    report = build_markov_validation_report(update_baseline=not args.no_update_baseline)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_markov_validation_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
