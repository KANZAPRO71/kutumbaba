"""Phase D.2 — metastability detection over constrained Markov dynamics.

Answers: "where is the system about to break?" using spectral gap, energy
landscape bottlenecks, escape probabilities, and critical regime cascades.

Requires frozen generation_id (D hardening) and validated kernel (D.1).
Diagnostics only — no gating.
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
    RegimeHalfLifeReport,
    TransitionMatrix,
    build_manifold_dynamics_report,
    compute_regime_half_life,
    extract_event_stream,
)
from persona_ai.diagnostics.runtime_soft_observer import RuntimeSoftTelemetryStore

METASTABILITY_VERSION = "v1"
DEFAULT_BASELINE_PATH = Path(".persona_ai/metastability_baseline.json")
BOUNDARY_REGIMES = {"I5", "I6"}
FAILURE_CASCADE = ("I2", "I4", "I5")
SELF_LOOP_BASIN_THRESHOLD = 0.25
BASIN_MERGE_THRESHOLD = 0.08
SPECTRAL_GAP_WARNING = 0.15
EPS = 1e-12


def _active_regimes(matrix: TransitionMatrix) -> list[str]:
    active: list[str] = []
    for regime in ALL_REGIMES:
        row = matrix.counts.get(regime, {})
        total = sum(row.values()) - len(ALL_REGIMES)
        if total > 0:
            active.append(regime)
    return active or list(ALL_REGIMES)


def _submatrix(
    probabilities: dict[str, dict[str, float]],
    regimes: list[str],
) -> list[list[float]]:
    return [[probabilities[source].get(target, EPS) for target in regimes] for source in regimes]


def _stationary_distribution(p_matrix: list[list[float]]) -> list[float]:
    n = len(p_matrix)
    pi = [1.0 / n] * n
    for _ in range(400):
        pi_new = [sum(pi[j] * p_matrix[j][i] for j in range(n)) for i in range(n)]
        total = sum(pi_new) or 1.0
        pi = [value / total for value in pi_new]
    return pi


def _subdominant_eigenvalue_magnitude(p_matrix: list[list[float]]) -> float:
    n = len(p_matrix)
    if n <= 1:
        return 0.0
    pi = _stationary_distribution(p_matrix)
    vector = [1.0 / math.sqrt(n) - pi[index] for index in range(n)]
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    vector = [value / norm for value in vector]
    for _ in range(300):
        projected = [sum(p_matrix[row][col] * vector[col] for col in range(n)) for row in range(n)]
        dot = sum(projected[index] * pi[index] for index in range(n))
        vector = [projected[index] - dot * pi[index] for index in range(n)]
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        vector = [value / norm for value in vector]
    eigenvalue = sum(
        vector[row] * sum(p_matrix[row][col] * vector[col] for col in range(n)) for row in range(n)
    )
    return abs(eigenvalue)


@dataclass
class SpectralGapReport:
    spectral_gap: float
    subdominant_eigenvalue: float
    mixing_time_proxy: float
    gap_collapsing: bool
    gap_delta_from_baseline: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_spectral_gap(
    matrix: TransitionMatrix,
    *,
    baseline_gap: float | None = None,
) -> SpectralGapReport:
    """Spectral gap 1 - |λ₂| — small gap ⇒ critical slowing down."""
    active = _active_regimes(matrix)
    p_matrix = _submatrix(matrix.probabilities, active)
    lambda2 = _subdominant_eigenvalue_magnitude(p_matrix)
    gap = round(1.0 - lambda2, 6)
    mixing = round(1.0 / max(gap, EPS), 4)
    gap_delta = round(gap - baseline_gap, 6) if baseline_gap is not None else None
    collapsing = gap < SPECTRAL_GAP_WARNING or (
        gap_delta is not None and gap_delta < -0.05
    )
    return SpectralGapReport(
        spectral_gap=gap,
        subdominant_eigenvalue=round(lambda2, 6),
        mixing_time_proxy=mixing,
        gap_collapsing=collapsing,
        gap_delta_from_baseline=gap_delta,
    )


@dataclass
class MetastableBasin:
    basin_id: str
    regimes: list[str]
    core_regime: str
    mean_self_loop: float
    escape_probability: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _union_find_parent(parent: dict[str, str], node: str) -> str:
    if parent[node] != node:
        parent[node] = _union_find_parent(parent, parent[node])
    return parent[node]


def extract_metastable_basins(matrix: TransitionMatrix) -> list[MetastableBasin]:
    """Group regimes into metastable basins via self-loop cores + merge rule."""
    active = _active_regimes(matrix)
    parent = {regime: regime for regime in active}
    for source in active:
        for target in active:
            if source == target:
                continue
            forward = matrix.probabilities[source].get(target, 0.0)
            backward = matrix.probabilities[target].get(source, 0.0)
            if forward >= BASIN_MERGE_THRESHOLD and backward >= BASIN_MERGE_THRESHOLD:
                root_a = _union_find_parent(parent, source)
                root_b = _union_find_parent(parent, target)
                parent[root_b] = root_a

    groups: dict[str, list[str]] = {}
    for regime in active:
        root = _union_find_parent(parent, regime)
        groups.setdefault(root, []).append(regime)

    basins: list[MetastableBasin] = []
    for index, regimes in enumerate(sorted(groups.values(), key=min)):
        regimes = sorted(regimes)
        self_loops = [matrix.probabilities[regime].get(regime, 0.0) for regime in regimes]
        core = max(regimes, key=lambda regime: matrix.probabilities[regime].get(regime, 0.0))
        escape = round(
            sum(
                sum(
                    matrix.probabilities[regime].get(target, 0.0)
                    for target in ALL_REGIMES
                    if target not in regimes
                )
                for regime in regimes
            )
            / max(len(regimes), 1),
            6,
        )
        basins.append(
            MetastableBasin(
                basin_id=f"basin_{index}",
                regimes=regimes,
                core_regime=core,
                mean_self_loop=round(sum(self_loops) / len(self_loops), 6),
                escape_probability=escape,
            )
        )
    return basins


@dataclass
class TransitionBottleneck:
    source: str
    target: str
    probability: float
    energy: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def find_transition_bottlenecks(
    matrix: TransitionMatrix,
    *,
    top_k: int = 5,
) -> list[TransitionBottleneck]:
    """Highest-energy observed transitions — slow escape channels."""
    bottlenecks: list[TransitionBottleneck] = []
    for source in ALL_REGIMES:
        for target in ALL_REGIMES:
            if source == target:
                continue
            probability = matrix.probabilities.get(source, {}).get(target, 0.0)
            if probability <= 0.01:
                continue
            energy = matrix.energy.get(source, {}).get(target, 0.0)
            bottlenecks.append(
                TransitionBottleneck(
                    source=source,
                    target=target,
                    probability=round(probability, 6),
                    energy=round(energy, 6),
                )
            )
    bottlenecks.sort(key=lambda item: (-item.energy, item.probability))
    return bottlenecks[:top_k]


@dataclass
class QuasiStationaryReport:
    restricted_regimes: list[str]
    quasi_stationary: dict[str, float]
    boundary_mass: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_quasi_stationary_distribution(matrix: TransitionMatrix) -> QuasiStationaryReport:
    """Stationary measure on non-boundary regimes (I0–I4)."""
    restricted = [regime for regime in ALL_REGIMES if regime not in BOUNDARY_REGIMES]
    sub = _submatrix(matrix.probabilities, restricted)
    row_sums = [sum(row) or 1.0 for row in sub]
    normalized = [[value / row_sums[row_index] for value in row] for row_index, row in enumerate(sub)]
    pi = _stationary_distribution(normalized)
    boundary_mass = round(
        sum(
            matrix.probabilities[source].get(target, 0.0)
            for source in restricted
            for target in BOUNDARY_REGIMES
        )
        / max(len(restricted), 1),
        6,
    )
    return QuasiStationaryReport(
        restricted_regimes=restricted,
        quasi_stationary={
            restricted[index]: round(pi[index], 6) for index in range(len(restricted))
        },
        boundary_mass=boundary_mass,
    )


@dataclass
class CriticalCascadeReport:
    cascade: list[str]
    path_probability: float
    path_energy: float
    critical_slowing_active: bool
    residence_anomaly_I4: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analyze_critical_cascade(
    matrix: TransitionMatrix,
    half_life: RegimeHalfLifeReport,
) -> CriticalCascadeReport:
    """Detect I2 → I4 → I5 tension cascade as phase-transition precursor."""
    source, middle, sink = FAILURE_CASCADE
    path_probability = round(
        matrix.probabilities.get(source, {}).get(middle, 0.0)
        * matrix.probabilities.get(middle, {}).get(sink, 0.0),
        6,
    )
    path_energy = round(
        matrix.energy.get(source, {}).get(middle, 0.0)
        + matrix.energy.get(middle, {}).get(sink, 0.0),
        6,
    )
    self_loop = matrix.probabilities.get(middle, {}).get(middle, 0.0)
    expected_residence = round(1.0 / max(1.0 - self_loop, EPS), 4)
    observed = half_life.half_life_events.get(middle, 0.0)
    anomaly = round((observed - expected_residence) / max(expected_residence, EPS), 6) if observed else 0.0
    slowing = anomaly > 0.35 and path_probability > 0.005
    return CriticalCascadeReport(
        cascade=list(FAILURE_CASCADE),
        path_probability=path_probability,
        path_energy=path_energy,
        critical_slowing_active=slowing,
        residence_anomaly_I4=anomaly,
    )


@dataclass
class BoundaryEarlyWarning:
    boundary_approach_score: float
    i5_escape_rate: float
    warning_active: bool
    drivers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_boundary_early_warning(
    matrix: TransitionMatrix,
    *,
    spectral: SpectralGapReport,
    cascade: CriticalCascadeReport,
) -> BoundaryEarlyWarning:
    """Early warning for I5 boundary approach before hard gate failure."""
    active = _active_regimes(matrix)
    p_matrix = _submatrix(matrix.probabilities, active)
    pi = _stationary_distribution(p_matrix)
    i5_index = active.index("I5") if "I5" in active else None
    score = 0.0
    if i5_index is not None:
        score = sum(
            pi[index] * matrix.probabilities[active[index]].get("I5", 0.0)
            for index in range(len(active))
        )
    i5_self = matrix.probabilities.get("I5", {}).get("I5", 0.0)
    i5_escape = round(1.0 - i5_self, 6)
    drivers: list[str] = []
    if score > 0.05:
        drivers.append("elevated_i5_influx")
    if spectral.gap_collapsing:
        drivers.append("spectral_gap_collapse")
    if cascade.critical_slowing_active:
        drivers.append("i2_i4_i5_cascade")
    if i5_escape > 0.4:
        drivers.append("i5_loop_instability")
    warning = score > 0.04 or (spectral.gap_collapsing and cascade.path_probability > 0.003)
    return BoundaryEarlyWarning(
        boundary_approach_score=round(score, 6),
        i5_escape_rate=i5_escape,
        warning_active=warning,
        drivers=drivers,
    )


@dataclass
class ResidenceAnomalyReport:
    expected_events: dict[str, float]
    observed_events: dict[str, float]
    anomaly_ratio: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_residence_anomalies(
    matrix: TransitionMatrix,
    half_life: RegimeHalfLifeReport,
) -> ResidenceAnomalyReport:
    """Compare observed half-life vs Markov-predicted residence time."""
    expected: dict[str, float] = {}
    observed: dict[str, float] = {}
    anomaly: dict[str, float] = {}
    for regime in ALL_REGIMES:
        self_loop = matrix.probabilities.get(regime, {}).get(regime, 0.0)
        if self_loop <= 0.0:
            continue
        predicted = round(1.0 / max(1.0 - self_loop, EPS), 4)
        expected[regime] = predicted
        if regime in half_life.half_life_events:
            observed[regime] = half_life.half_life_events[regime]
            anomaly[regime] = round(
                (observed[regime] - predicted) / max(predicted, EPS),
                6,
            )
    return ResidenceAnomalyReport(
        expected_events=expected,
        observed_events=observed,
        anomaly_ratio=anomaly,
    )


@dataclass
class MetastabilityBaselineStore:
    path: Path = field(default_factory=lambda: DEFAULT_BASELINE_PATH)
    spectral_gap: float | None = None
    boundary_approach_score: float | None = None
    generation_id: str | None = None

    def __post_init__(self) -> None:
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.spectral_gap = raw.get("spectral_gap")
        self.boundary_approach_score = raw.get("boundary_approach_score")
        self.generation_id = raw.get("generation_id")

    def save(
        self,
        *,
        spectral_gap: float,
        boundary_approach_score: float,
        generation_id: str,
    ) -> None:
        self.spectral_gap = spectral_gap
        self.boundary_approach_score = boundary_approach_score
        self.generation_id = generation_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metastability_version": METASTABILITY_VERSION,
            "spectral_gap": spectral_gap,
            "boundary_approach_score": boundary_approach_score,
            "generation_id": generation_id,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@dataclass
class MetastabilityReport:
    version: str
    generation_id: str | None
    sufficient_samples: bool
    spectral_gap: SpectralGapReport
    metastable_basins: list[MetastableBasin]
    bottlenecks: list[TransitionBottleneck]
    quasi_stationary: QuasiStationaryReport
    critical_cascade: CriticalCascadeReport
    boundary_warning: BoundaryEarlyWarning
    residence_anomalies: ResidenceAnomalyReport
    diagnostics_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "metastability_version": self.version,
            "generation_id": self.generation_id,
            "sufficient_samples": self.sufficient_samples,
            "spectral_gap": self.spectral_gap.to_dict(),
            "metastable_basins": [basin.to_dict() for basin in self.metastable_basins],
            "bottlenecks": [item.to_dict() for item in self.bottlenecks],
            "quasi_stationary": self.quasi_stationary.to_dict(),
            "critical_cascade": self.critical_cascade.to_dict(),
            "boundary_warning": self.boundary_warning.to_dict(),
            "residence_anomalies": self.residence_anomalies.to_dict(),
            "diagnostics_only": self.diagnostics_only,
        }


def build_metastability_report(
    *,
    ci_store: ArbitrationTelemetryStore | None = None,
    runtime_store: RuntimeSoftTelemetryStore | None = None,
    baseline_store: MetastabilityBaselineStore | None = None,
    update_baseline: bool = False,
) -> MetastabilityReport:
    events = extract_event_stream(ci_store=ci_store, runtime_store=runtime_store)
    dynamics = build_manifold_dynamics_report(ci_store=ci_store, runtime_store=runtime_store)
    matrix = dynamics.transition_matrix
    generation_id = matrix.generation_id if matrix else None

    empty_spectral = SpectralGapReport(0.0, 0.0, 0.0, False, None)
    empty_quasi = QuasiStationaryReport([], {}, 0.0)
    empty_cascade = CriticalCascadeReport(list(FAILURE_CASCADE), 0.0, 0.0, False, 0.0)
    empty_warning = BoundaryEarlyWarning(0.0, 0.0, False, [])
    empty_residence = ResidenceAnomalyReport({}, {}, {})

    if matrix is None or matrix.sample_transitions < MIN_EVENTS_FOR_MATRIX:
        return MetastabilityReport(
            version=METASTABILITY_VERSION,
            generation_id=generation_id,
            sufficient_samples=False,
            spectral_gap=empty_spectral,
            metastable_basins=[],
            bottlenecks=[],
            quasi_stationary=empty_quasi,
            critical_cascade=empty_cascade,
            boundary_warning=empty_warning,
            residence_anomalies=empty_residence,
        )

    baseline = baseline_store or MetastabilityBaselineStore()
    baseline_gap = (
        baseline.spectral_gap
        if baseline.generation_id == generation_id and baseline.spectral_gap is not None
        else None
    )
    spectral = analyze_spectral_gap(matrix, baseline_gap=baseline_gap)
    basins = extract_metastable_basins(matrix)
    bottlenecks = find_transition_bottlenecks(matrix)
    quasi = compute_quasi_stationary_distribution(matrix)
    half_life = compute_regime_half_life(events)
    cascade = analyze_critical_cascade(matrix, half_life)
    warning = compute_boundary_early_warning(matrix, spectral=spectral, cascade=cascade)
    residence = compute_residence_anomalies(matrix, half_life)

    if update_baseline and generation_id:
        baseline.save(
            spectral_gap=spectral.spectral_gap,
            boundary_approach_score=warning.boundary_approach_score,
            generation_id=generation_id,
        )

    return MetastabilityReport(
        version=METASTABILITY_VERSION,
        generation_id=generation_id,
        sufficient_samples=True,
        spectral_gap=spectral,
        metastable_basins=basins,
        bottlenecks=bottlenecks,
        quasi_stationary=quasi,
        critical_cascade=cascade,
        boundary_warning=warning,
        residence_anomalies=residence,
    )


def format_metastability_report(report: MetastabilityReport) -> str:
    lines = [
        f"=== Metastability Detection | Phase D.2 {report.version} ===",
        f"  generation={report.generation_id or 'n/a'} samples={report.sufficient_samples}",
    ]
    if not report.sufficient_samples:
        lines.append("  insufficient transitions for metastability analysis")
        return "\n".join(lines)

    spectral = report.spectral_gap
    lines.extend(
        [
            "",
            "  SPECTRAL GAP",
            f"    gap={spectral.spectral_gap:.4f} λ₂={spectral.subdominant_eigenvalue:.4f} "
            f"mixing~{spectral.mixing_time_proxy:.1f} collapsing={spectral.gap_collapsing}",
        ]
    )
    if spectral.gap_delta_from_baseline is not None:
        lines.append(f"    Δgap={spectral.gap_delta_from_baseline:+.4f}")

    if report.metastable_basins:
        lines.append("")
        lines.append("  METASTABLE BASINS")
        for basin in report.metastable_basins:
            lines.append(
                f"    {basin.basin_id} core={basin.core_regime} "
                f"regimes={','.join(basin.regimes)} "
                f"self_loop={basin.mean_self_loop:.3f} escape={basin.escape_probability:.3f}"
            )

    if report.bottlenecks:
        lines.append("")
        lines.append("  BOTTLENECKS (high energy transitions)")
        for item in report.bottlenecks[:4]:
            lines.append(
                f"    {item.source}->{item.target} P={item.probability:.3f} H={item.energy:.3f}"
            )

    cascade = report.critical_cascade
    lines.extend(
        [
            "",
            "  CRITICAL CASCADE",
            f"    {'->'.join(cascade.cascade)} P={cascade.path_probability:.4f} "
            f"H={cascade.path_energy:.3f} slowing={cascade.critical_slowing_active}",
        ]
    )

    warning = report.boundary_warning
    lines.extend(
        [
            "",
            "  BOUNDARY EARLY WARNING",
            f"    score={warning.boundary_approach_score:.4f} "
            f"active={warning.warning_active} drivers={warning.drivers or ['none']}",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Metastability detection — Phase D.2")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args(argv)

    report = build_metastability_report(update_baseline=args.update_baseline)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_metastability_report(report))
    return 1 if report.boundary_warning.warning_active else 0


if __name__ == "__main__":
    raise SystemExit(main())
