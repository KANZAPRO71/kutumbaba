"""Promotion Gate v1 — trusted learning admission control (shadow → promoted memory).

Sits between shadow_comparator and trusted fast-path eligibility.
Does NOT overwrite fingerprint_learning.json — writes promoted_learnings.json only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from persona_ai.diagnostics.shadow_comparator import (
    FingerprintShadowComparison,
    ShadowComparator,
    ShadowReport,
)

PROMOTION_VERSION = "v1"
DEFAULT_STORE_PATH = Path(".persona_ai/promoted_learnings.json")

LifecycleStatus = Literal["active", "degraded", "quarantined", "demoted"]
TRUSTED_STATUSES: frozenset[str] = frozenset({"active"})

MIN_STABILITY = 0.85
MIN_PROD_OCCURRENCES = 3
MAX_SCORE_DELTA = 0.20

RejectionCode = Literal[
    "OVERFIT",
    "UNDERMODELED",
    "NOISE",
    "UNSTABLE",
    "DRIFT",
    "NOT_VALIDATED",
    "WATCH",
    None,
]

DecisionStatus = Literal["PROMOTED", "REJECTED"]


@dataclass
class PromotionDecision:
    fp_id: str
    patch_id: str
    status: DecisionStatus
    confidence: float
    reasons: list[str]
    rejection_code: RejectionCode = None
    promotion_version: str = PROMOTION_VERSION
    stability: float = 0.0
    sim_score: float = 0.0
    prod_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PromotedLearning:
    fp_id: str
    patch_id: str
    first_promoted: str
    last_evaluated: str
    stability: float
    confidence: float
    source: str = "shadow_v1"
    status: LifecycleStatus = "active"
    promotion_version: str = PROMOTION_VERSION
    reasons: list[str] = field(default_factory=list)
    baseline_stability: float = 0.0
    baseline_prod_score: float = 0.0
    baseline_sim_score: float = 0.0
    last_status_change: str = ""
    false_promotion_class: str | None = None
    monitoring_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PromotionReport:
    decisions: list[PromotionDecision]
    promoted_count: int
    rejected_count: int
    active_promoted: int
    debug_trace: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decisions": [d.to_dict() for d in self.decisions],
            "promoted_count": self.promoted_count,
            "rejected_count": self.rejected_count,
            "active_promoted": self.active_promoted,
        }


def _sim_score(row: FingerprintShadowComparison) -> float:
    if row.simulation.decayed_score is not None:
        return row.simulation.decayed_score
    return row.simulation.success_rate


def _prod_score(row: FingerprintShadowComparison) -> float:
    return row.production.success_rate


def evaluate_comparison(row: FingerprintShadowComparison) -> PromotionDecision:
    patch_id = row.simulation.primary_patch or "unknown"
    sim_s = _sim_score(row)
    prod_s = _prod_score(row)
    score_delta = abs(sim_s - prod_s)
    reasons: list[str] = []
    rejection: RejectionCode = None

    if row.classification == "simulation_overfit":
        rejection = "OVERFIT"
        reasons.append("simulation_overfit")
    elif row.classification == "undermodeled":
        rejection = "UNDERMODELED"
        reasons.append("undermodeled_shadow")
    elif row.classification == "noise":
        rejection = "NOISE"
        reasons.append("insufficient_production_frequency")
    elif row.classification == "watch":
        rejection = "WATCH"
        reasons.append("borderline_generalization_gap")
    elif row.classification != "validated":
        rejection = "NOT_VALIDATED"
        reasons.append(f"classification_{row.classification}")

    if row.production.occurrences < MIN_PROD_OCCURRENCES:
        rejection = rejection or "NOISE"
        reasons.append(f"prod_occurrences<{MIN_PROD_OCCURRENCES}")

    if row.stability < MIN_STABILITY:
        rejection = rejection or "UNSTABLE"
        reasons.append(f"stability<{MIN_STABILITY}")

    if score_delta > MAX_SCORE_DELTA:
        rejection = rejection or "DRIFT"
        reasons.append(f"score_delta>{MAX_SCORE_DELTA}")

    if rejection is None:
        reasons.extend([
            "validated_shadow_match",
            "stable_cross_domain",
            "sufficient_frequency",
            "consistent_behavioral_strength",
        ])
        confidence = round(min(1.0, row.stability * (1.0 - score_delta)), 3)
        return PromotionDecision(
            fp_id=row.fp_id,
            patch_id=patch_id,
            status="PROMOTED",
            confidence=confidence,
            reasons=reasons,
            stability=row.stability,
            sim_score=sim_s,
            prod_score=prod_s,
        )

    return PromotionDecision(
        fp_id=row.fp_id,
        patch_id=patch_id,
        status="REJECTED",
        confidence=round(row.stability * 0.5, 3),
        reasons=reasons,
        rejection_code=rejection,
        stability=row.stability,
        sim_score=sim_s,
        prod_score=prod_s,
    )


class PromotedLearningStore:
    """Trusted subset of (fp_id, patch_id) pairs allowed for fast-path acceleration."""

    def __init__(self, store_path: Path | None = None):
        self.store_path = store_path or DEFAULT_STORE_PATH
        self.entries: dict[str, PromotedLearning] = {}
        if self.store_path.exists():
            self._load()

    def _key(self, fp_id: str, patch_id: str) -> str:
        return f"{fp_id}::{patch_id}"

    def _load(self) -> None:
        raw = json.loads(self.store_path.read_text(encoding="utf-8"))
        for item in raw.get("entries", []):
            key = self._key(item["fp_id"], item["patch_id"])
            item.setdefault("baseline_stability", item.get("stability", 0.0))
            item.setdefault("baseline_prod_score", 0.0)
            item.setdefault("baseline_sim_score", 0.0)
            item.setdefault("last_status_change", item.get("first_promoted", ""))
            item.setdefault("false_promotion_class", None)
            item.setdefault("monitoring_flags", [])
            self.entries[key] = PromotedLearning(**item)

    def get(self, fp_id: str, patch_id: str) -> PromotedLearning | None:
        return self.entries.get(self._key(fp_id, patch_id))

    def is_promoted(self, fp_id: str, patch_id: str) -> bool:
        entry = self.entries.get(self._key(fp_id, patch_id))
        return entry is not None and entry.status in TRUSTED_STATUSES

    def is_trusted(self, fp_id: str, patch_id: str) -> bool:
        return self.is_promoted(fp_id, patch_id)

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "promotion_version": PROMOTION_VERSION,
            "entries": [e.to_dict() for e in self.entries.values()],
        }
        self.store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def apply_lifecycle_update(
        self,
        fp_id: str,
        patch_id: str,
        *,
        status: LifecycleStatus,
        false_promotion_class: str | None = None,
        monitoring_flags: list[str] | None = None,
        stability: float | None = None,
    ) -> bool:
        entry = self.get(fp_id, patch_id)
        if entry is None:
            return False
        now = datetime.now(timezone.utc).isoformat()
        if entry.status != status:
            entry.last_status_change = now
        entry.status = status
        entry.last_evaluated = now
        if false_promotion_class is not None:
            entry.false_promotion_class = false_promotion_class
        if monitoring_flags is not None:
            entry.monitoring_flags = list(monitoring_flags)
        if stability is not None:
            entry.stability = stability
        return True

    def apply_decisions(self, decisions: list[PromotionDecision]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        applied = 0
        for decision in decisions:
            if decision.status != "PROMOTED":
                continue
            key = self._key(decision.fp_id, decision.patch_id)
            existing = self.entries.get(key)
            if existing is None:
                self.entries[key] = PromotedLearning(
                    fp_id=decision.fp_id,
                    patch_id=decision.patch_id,
                    first_promoted=now,
                    last_evaluated=now,
                    last_status_change=now,
                    stability=decision.stability,
                    confidence=decision.confidence,
                    reasons=list(decision.reasons),
                    baseline_stability=decision.stability,
                    baseline_prod_score=decision.prod_score,
                    baseline_sim_score=decision.sim_score,
                )
            else:
                existing.last_evaluated = now
                existing.stability = decision.stability
                existing.confidence = decision.confidence
                existing.reasons = list(decision.reasons)
                if existing.status in ("demoted", "quarantined"):
                    existing.status = "active"
                    existing.last_status_change = now
                    existing.false_promotion_class = None
                    existing.monitoring_flags = []
                existing.baseline_stability = decision.stability
                existing.baseline_prod_score = decision.prod_score
                existing.baseline_sim_score = decision.sim_score
            applied += 1
        return applied

    @property
    def active_count(self) -> int:
        return sum(1 for e in self.entries.values() if e.status == "active")

    @property
    def monitored_count(self) -> int:
        return sum(
            1 for e in self.entries.values() if e.status in ("active", "degraded", "quarantined")
        )

    def promoted_entries(self) -> list[PromotedLearning]:
        return list(self.entries.values())


class PromotionGate:
    """Evaluates shadow comparisons for trusted learning admission."""

    def __init__(self, store: PromotedLearningStore | None = None):
        self.store = store or PromotedLearningStore()

    def evaluate(self, shadow: ShadowReport) -> list[PromotionDecision]:
        return [evaluate_comparison(row) for row in shadow.comparisons]

    def run(
        self,
        *,
        comparator: ShadowComparator | None = None,
        persist: bool = False,
    ) -> PromotionReport:
        comparator = comparator or ShadowComparator()
        shadow = comparator.build_report()
        decisions = self.evaluate(shadow)
        if persist:
            self.store.apply_decisions(decisions)
            self.store.save()

        promoted = sum(1 for d in decisions if d.status == "PROMOTED")
        rejected = sum(1 for d in decisions if d.status == "REJECTED")
        report = PromotionReport(
            decisions=decisions,
            promoted_count=promoted,
            rejected_count=rejected,
            active_promoted=self.store.active_count,
        )
        report.debug_trace = format_promotion_trace(report)
        return report


def format_promotion_trace(report: PromotionReport) -> str:
    lines = [
        "=== Promotion Gate | trusted learning admission (v1) ===",
        f"  evaluated: {len(report.decisions)} | promoted: {report.promoted_count} | "
        f"rejected: {report.rejected_count} | active store: {report.active_promoted}",
        "  fast-path reads promoted set ONLY (suggestion layer unchanged)",
    ]
    for decision in report.decisions:
        if decision.status == "PROMOTED":
            lines.append(
                f"\n  [PROMOTED] {decision.fp_id} -> {decision.patch_id} "
                f"conf={decision.confidence:.2f} stability={decision.stability:.2f}"
            )
            lines.append(f"    reasons: {', '.join(decision.reasons)}")
        elif decision.rejection_code:
            lines.append(
                f"\n  [REJECTED:{decision.rejection_code}] {decision.fp_id} -> {decision.patch_id}"
            )
            lines.append(f"    reasons: {', '.join(decision.reasons)}")
    if report.promoted_count == 0 and not report.decisions:
        lines.append("\n  No shadow comparisons available for promotion evaluation.")
    return "\n".join(lines)


_default_store: PromotedLearningStore | None = None


def get_promoted_store(store_path: Path | None = None) -> PromotedLearningStore:
    global _default_store
    if _default_store is None:
        path = store_path or DEFAULT_STORE_PATH
        _default_store = PromotedLearningStore(path)
    return _default_store


def is_trusted_for_fast_path(fp_id: str, patch_id: str) -> bool:
    return get_promoted_store().is_promoted(fp_id, patch_id)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Promotion gate — trusted learning admission")
    parser.add_argument("--persist", action="store_true", help="Write promoted entries to store")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--learning", type=Path, default=None)
    parser.add_argument("--ingest", type=Path, default=None)
    args = parser.parse_args(argv)

    comparator = ShadowComparator(
        learning_path=args.learning,
        ingest_path=args.ingest,
    )

    gate = PromotionGate(PromotedLearningStore(args.store))
    report = gate.run(comparator=comparator, persist=args.persist)

    if args.json:
        payload = report.to_dict()
        payload["trace"] = report.debug_trace
        print(json.dumps(payload, indent=2))
    else:
        print(report.debug_trace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
