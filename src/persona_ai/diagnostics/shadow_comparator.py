"""Shadow comparison v1 — simulation vs production truth alignment (read-only).

Compares fingerprint_learning.json (synthetic) against production_ingest_log.json (reality).
No write-back to learning or runtime behavior.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from persona_ai.diagnostics.fingerprint_learning import (
    DEFAULT_STORE_PATH as LEARNING_STORE_PATH,
    FingerprintPatchLearner,
)
from persona_ai.diagnostics.production_ingest import DEFAULT_LOG_PATH as INGEST_LOG_PATH

Classification = Literal["validated", "simulation_overfit", "undermodeled", "noise", "watch"]

VALIDATED_GAP = 0.15
OVERFIT_GAP = 0.30
UNDERMODELED_GAP = -0.15
MIN_PROD_OCCURRENCES = 2


@dataclass
class DomainMetrics:
    success_rate: float
    attempts: int = 0
    occurrences: int = 0
    failure_rate: float = 0.0
    decayed_score: float | None = None
    confidence: float = 0.0
    primary_patch: str | None = None


@dataclass
class ShadowDelta:
    success_gap: float
    confidence_gap: float
    score_gap: float | None = None


@dataclass
class FingerprintShadowComparison:
    fp_id: str
    semantic_key: str
    simulation: DomainMetrics
    production: DomainMetrics
    delta: ShadowDelta
    classification: Classification
    stability: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "fp_id": self.fp_id,
            "semantic_key": self.semantic_key,
            "simulation": asdict(self.simulation),
            "production": asdict(self.production),
            "delta": asdict(self.delta),
            "classification": self.classification,
            "stability": self.stability,
        }


@dataclass
class PatchShadowSummary:
    patch_id: str
    sim_success_rate: float
    prod_success_rate: float
    fp_count: int
    classification: Classification


@dataclass
class DriftTimelinePoint:
    session_id: str
    timestamp: str
    avg_success_gap: float
    fingerprint_count: int


@dataclass
class ShadowReport:
    comparisons: list[FingerprintShadowComparison]
    patch_summaries: list[PatchShadowSummary]
    timeline: list[DriftTimelinePoint]
    avg_generalization_gap: float
    validated_pct: float
    overfit_pct: float
    undermodeled_pct: float
    noise_pct: float
    affects_runtime: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparisons": [c.to_dict() for c in self.comparisons],
            "patch_summaries": [asdict(p) for p in self.patch_summaries],
            "timeline": [asdict(t) for t in self.timeline],
            "summary": {
                "avg_generalization_gap": self.avg_generalization_gap,
                "validated_pct": self.validated_pct,
                "overfit_pct": self.overfit_pct,
                "undermodeled_pct": self.undermodeled_pct,
                "noise_pct": self.noise_pct,
                "affects_runtime": self.affects_runtime,
            },
        }


def load_production_entries(log_path: Path | None = None) -> list[dict[str, Any]]:
    path = log_path or INGEST_LOG_PATH
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return list(raw.get("entries", []))


def aggregate_production_metrics(
    entries: list[dict[str, Any]],
) -> tuple[dict[str, DomainMetrics], dict[str, str]]:
    """Aggregate production outcomes by fp_id."""
    counts: dict[str, dict[str, int]] = {}
    semantic: dict[str, str] = {}

    success_outcomes = {"observed_success", "partial_success"}
    fail_outcomes = {"observed_failure", "degraded"}

    for entry in entries:
        for obs in entry.get("fingerprints", []):
            fp_id = obs["fp_id"]
            semantic.setdefault(fp_id, obs.get("semantic_key", ""))
            bucket = counts.setdefault(fp_id, {"total": 0, "success": 0, "fail": 0})
            bucket["total"] += 1
            outcome = obs.get("outcome", "observed")
            if outcome in success_outcomes:
                bucket["success"] += 1
            elif outcome in fail_outcomes:
                bucket["fail"] += 1

    metrics: dict[str, DomainMetrics] = {}
    for fp_id, bucket in counts.items():
        total = bucket["total"]
        success = bucket["success"]
        fail = bucket["fail"]
        metrics[fp_id] = DomainMetrics(
            success_rate=round(success / max(total, 1), 3),
            occurrences=total,
            failure_rate=round(fail / max(total, 1), 3),
            confidence=round(total / (total + 2), 3),
        )
    return metrics, semantic


def aggregate_simulation_metrics(
    learner: FingerprintPatchLearner,
) -> dict[str, DomainMetrics]:
    """Aggregate simulation (learning store) metrics by fp_id — best patch view."""
    out: dict[str, DomainMetrics] = {}
    for fp_id, patches in learner._store.items():
        if not patches:
            continue
        preds = learner.predict_best(fp_id, sorted(patches.keys()))
        if not preds:
            continue
        top = preds[0]
        stats = patches[top.patch_id]
        out[fp_id] = DomainMetrics(
            success_rate=round(stats.success / max(stats.attempts, 1), 3),
            attempts=stats.attempts,
            decayed_score=top.decayed_score,
            confidence=top.confidence,
            primary_patch=top.patch_id,
        )
    return out


def classify_comparison(
    gap: float,
    *,
    sim: DomainMetrics,
    prod: DomainMetrics,
) -> Classification:
    if prod.occurrences < MIN_PROD_OCCURRENCES and sim.attempts < 2:
        return "noise"
    if prod.occurrences < MIN_PROD_OCCURRENCES:
        return "noise"
    if gap > OVERFIT_GAP:
        return "simulation_overfit"
    if gap < UNDERMODELED_GAP:
        return "undermodeled"
    if abs(gap) <= VALIDATED_GAP:
        return "validated"
    return "watch"


def compute_stability(sim: DomainMetrics, prod: DomainMetrics) -> float:
    """P(fp behaves similarly in prod vs sim) — symmetric agreement proxy."""
    if prod.occurrences == 0 and sim.attempts == 0:
        return 0.0
    gap = abs(sim.success_rate - prod.success_rate)
    return round(max(0.0, 1.0 - gap), 3)


class ShadowComparator:
    """Read-only simulation vs production comparator keyed by fingerprint_id."""

    def __init__(
        self,
        *,
        learning_path: Path | None = None,
        ingest_path: Path | None = None,
    ):
        self.learning_path = learning_path or LEARNING_STORE_PATH
        self.ingest_path = ingest_path or INGEST_LOG_PATH

    def compare_fp(self, fp_id: str) -> FingerprintShadowComparison | None:
        report = self.build_report()
        for row in report.comparisons:
            if row.fp_id == fp_id:
                return row
        return None

    def build_report(self) -> ShadowReport:
        learner = FingerprintPatchLearner(self.learning_path)
        prod_entries = load_production_entries(self.ingest_path)
        sim_by_fp = aggregate_simulation_metrics(learner)
        prod_by_fp, semantic = aggregate_production_metrics(prod_entries)

        all_fps = sorted(set(sim_by_fp) | set(prod_by_fp))
        comparisons: list[FingerprintShadowComparison] = []

        for fp_id in all_fps:
            sim = sim_by_fp.get(fp_id, DomainMetrics(success_rate=0.5, attempts=0))
            prod = prod_by_fp.get(fp_id, DomainMetrics(success_rate=0.5, occurrences=0))
            gap = round(sim.success_rate - prod.success_rate, 3)
            conf_gap = round(sim.confidence - prod.confidence, 3)
            score_gap = None
            if sim.decayed_score is not None:
                score_gap = round(sim.decayed_score - prod.success_rate, 3)
            classification = classify_comparison(gap, sim=sim, prod=prod)
            comparisons.append(
                FingerprintShadowComparison(
                    fp_id=fp_id,
                    semantic_key=semantic.get(fp_id, ""),
                    simulation=sim,
                    production=prod,
                    delta=ShadowDelta(
                        success_gap=gap,
                        confidence_gap=conf_gap,
                        score_gap=score_gap,
                    ),
                    classification=classification,
                    stability=compute_stability(sim, prod),
                )
            )

        comparisons.sort(key=lambda c: -abs(c.delta.success_gap))

        patch_summaries = _build_patch_summaries(comparisons)
        timeline = _build_drift_timeline(prod_entries, sim_by_fp)

        labels = [c.classification for c in comparisons]
        total = max(len(labels), 1)

        gaps = [c.delta.success_gap for c in comparisons if c.classification != "noise"]
        avg_gap = round(sum(gaps) / max(len(gaps), 1), 3) if gaps else 0.0

        return ShadowReport(
            comparisons=comparisons,
            patch_summaries=patch_summaries,
            timeline=timeline,
            avg_generalization_gap=avg_gap,
            validated_pct=round(labels.count("validated") / total, 3),
            overfit_pct=round(labels.count("simulation_overfit") / total, 3),
            undermodeled_pct=round(labels.count("undermodeled") / total, 3),
            noise_pct=round(labels.count("noise") / total, 3),
            affects_runtime=False,
        )


def _build_patch_summaries(
    comparisons: list[FingerprintShadowComparison],
) -> list[PatchShadowSummary]:
    by_patch: dict[str, list[FingerprintShadowComparison]] = {}
    for row in comparisons:
        patch = row.simulation.primary_patch
        if not patch:
            continue
        by_patch.setdefault(patch, []).append(row)

    summaries: list[PatchShadowSummary] = []
    for patch_id, rows in by_patch.items():
        sim_avg = sum(r.simulation.success_rate for r in rows) / len(rows)
        prod_rows = [r for r in rows if r.production.occurrences > 0]
        prod_avg = (
            sum(r.production.success_rate for r in prod_rows) / len(prod_rows)
            if prod_rows
            else 0.0
        )
        gap = sim_avg - prod_avg
        summaries.append(
            PatchShadowSummary(
                patch_id=patch_id,
                sim_success_rate=round(sim_avg, 3),
                prod_success_rate=round(prod_avg, 3),
                fp_count=len(rows),
                classification=classify_comparison(
                    gap,
                    sim=DomainMetrics(success_rate=sim_avg, attempts=1),
                    prod=DomainMetrics(success_rate=prod_avg, occurrences=len(prod_rows)),
                ),
            )
        )
    summaries.sort(key=lambda s: -abs(s.sim_success_rate - s.prod_success_rate))
    return summaries


def _build_drift_timeline(
    entries: list[dict[str, Any]],
    sim_by_fp: dict[str, DomainMetrics],
) -> list[DriftTimelinePoint]:
    timeline: list[DriftTimelinePoint] = []
    for entry in entries:
        fps = entry.get("fingerprints", [])
        if not fps:
            continue
        gaps: list[float] = []
        for obs in fps:
            fp_id = obs["fp_id"]
            sim = sim_by_fp.get(fp_id)
            if sim is None:
                continue
            outcome = obs.get("outcome", "observed")
            prod_success = 1.0 if outcome in ("observed_success", "partial_success") else 0.0
            if outcome == "degraded":
                prod_success = 0.5
            gaps.append(sim.success_rate - prod_success)
        if not gaps:
            continue
        timeline.append(
            DriftTimelinePoint(
                session_id=entry.get("session_id", "?"),
                timestamp=entry.get("timestamp", ""),
                avg_success_gap=round(sum(gaps) / len(gaps), 3),
                fingerprint_count=len(fps),
            )
        )
    return timeline


def format_shadow_report(report: ShadowReport) -> str:
    if not report.comparisons and not report.timeline:
        return (
            "=== Shadow Comparison | no data ===\n"
            "Need simulation learning store AND production ingest observations.\n"
            "  python -m persona_ai.sim.smoke_openai sarcasm_stack --record --observe"
        )

    lines = [
        "=== Shadow Comparison | simulation vs production ===",
        f"avg generalization gap (G): {report.avg_generalization_gap:+.3f}",
        f"validated: {report.validated_pct:.0%} | overfit: {report.overfit_pct:.0%} | "
        f"undermodeled: {report.undermodeled_pct:.0%} | noise: {report.noise_pct:.0%}",
        f"affects_runtime: {report.affects_runtime} (read-only truth alignment)",
        "",
        "=== Panel A | System Health ===",
        f"  G = sim_success - prod_success (target ~0, >0.3 overfit, <0 undermodeled)",
        "",
        "=== Panel B | Top Risky Fingerprints ===",
    ]

    risky = [c for c in report.comparisons if c.classification != "noise"][:8]
    if not risky:
        lines.append("  (no fingerprint overlaps yet)")
    for row in risky:
        lines.append(f"  {row.fp_id} [{row.classification.upper()}] stability={row.stability:.2f}")
        lines.append(
            f"    sim: {row.simulation.success_rate:.2f} success ({row.simulation.attempts} attempts) "
            f"decayed={row.simulation.decayed_score}"
        )
        lines.append(
            f"    prod: {row.production.success_rate:.2f} success ({row.production.occurrences} occurrences) "
            f"fail={row.production.failure_rate:.2f}"
        )
        lines.append(f"    delta G={row.delta.success_gap:+.2f}")

    lines.extend(["", "=== Panel C | Patch Reliability Leaderboard ==="])
    if not report.patch_summaries:
        lines.append("  (no patch overlap)")
    for patch in report.patch_summaries[:6]:
        label = "stable" if patch.classification == "validated" else patch.classification
        lines.append(
            f"  {patch.patch_id} -> {label} "
            f"(sim {patch.sim_success_rate:.2f} / prod {patch.prod_success_rate:.2f}, n_fp={patch.fp_count})"
        )

    lines.extend(["", "=== Panel D | Drift Timeline ==="])
    if not report.timeline:
        lines.append("  (no production timeline yet)")
    for point in report.timeline[-8:]:
        ts = point.timestamp[:19] if point.timestamp else "?"
        lines.append(
            f"  {point.session_id[:20]:20s} | G={point.avg_success_gap:+.2f} | fps={point.fingerprint_count} | {ts}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Shadow comparison dashboard (sim vs prod)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--learning", type=Path, default=LEARNING_STORE_PATH)
    parser.add_argument("--ingest", type=Path, default=INGEST_LOG_PATH)
    args = parser.parse_args(argv)

    comparator = ShadowComparator(learning_path=args.learning, ingest_path=args.ingest)
    report = comparator.build_report()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_shadow_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
