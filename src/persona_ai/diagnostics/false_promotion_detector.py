"""False Promotion Detection v1 — post-promotion truth pressure (corrective immune system).

Monitors promoted_learnings.json against production_ingest + shadow comparator.
Lifecycle: candidate -> promoted -> monitored -> validated | degraded | quarantined | demoted
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from persona_ai.diagnostics.promotion_gate import (
    DEFAULT_STORE_PATH,
    LifecycleStatus,
    PromotedLearning,
    PromotedLearningStore,
)
from persona_ai.diagnostics.shadow_comparator import (
    FingerprintShadowComparison,
    ShadowComparator,
    load_production_entries,
)

DETECTOR_VERSION = "v1"
DEFAULT_AUDIT_PATH = Path(".persona_ai/false_promotion_audit.json")

POST_PROMOTION_FAILURE_THRESHOLD = 0.5
STABILITY_COLLAPSE_DELTA = 0.25
CONTEXT_SHIFT_THRESHOLD = 0.40
SCORE_GAP_OVERFIT = 0.35
MIN_POST_PROMOTION_OBS = 2

DetectionFlag = Literal[
    "post_promotion_failure",
    "unstable_generalization",
    "context_shift_mismatch",
    "shadow_overconfidence",
]

FalsePromotionClass = Literal[
    "PREMATURE_PROMOTION",
    "SIMULATION_BIAS",
    "CONTEXT_SHIFT",
    "FREQUENCY_ILLUSION",
    "OVERFITTED_PROMOTION",
]

LifecycleAction = Literal[
    "maintain",
    "monitor",
    "degrade",
    "quarantine",
    "demote",
    "remove_from_fast_path",
]


@dataclass
class FalsePromotionEvidence:
    prod_success_rate: float = 0.0
    prod_drop: float = 0.0
    sim_prod_gap: float = 0.0
    stability_current: float = 0.0
    stability_decay: float = 0.0
    prod_occurrences: int = 0
    shadow_classification: str = ""
    context_shift_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FalsePromotionFinding:
    fp_id: str
    patch_id: str
    status: LifecycleStatus
    reason: str
    false_promotion_class: FalsePromotionClass
    severity: float
    action: LifecycleAction
    flags: list[str]
    evidence: FalsePromotionEvidence
    previous_status: LifecycleStatus = "active"

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["evidence"] = self.evidence.to_dict()
        return row


@dataclass
class FalsePromotionReport:
    findings: list[FalsePromotionFinding]
    evaluated: int
    flagged: int
    degraded_count: int
    quarantined_count: int
    demoted_count: int
    false_promotion_rate: float | None
    total_promotions: int
    false_promotions: int
    debug_trace: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector_version": DETECTOR_VERSION,
            "evaluated": self.evaluated,
            "flagged": self.flagged,
            "degraded_count": self.degraded_count,
            "quarantined_count": self.quarantined_count,
            "demoted_count": self.demoted_count,
            "false_promotion_rate": self.false_promotion_rate,
            "total_promotions": self.total_promotions,
            "false_promotions": self.false_promotions,
            "findings": [f.to_dict() for f in self.findings],
        }


def _context_distribution(
    entries: list[dict[str, Any]],
    fp_id: str,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for entry in entries:
        ctx = entry.get("context", "unknown")
        for obs in entry.get("fingerprints", []):
            if obs.get("fp_id") == fp_id:
                counts[ctx or "unknown"] += 1
    return counts


def _context_shift_score(
    entries: list[dict[str, Any]],
    fp_id: str,
) -> float:
    """Measure how much observation context mix shifted (first half vs second half)."""
    relevant: list[tuple[str, str]] = []
    for entry in entries:
        ctx = entry.get("context", "unknown") or "unknown"
        for obs in entry.get("fingerprints", []):
            if obs.get("fp_id") == fp_id:
                relevant.append((entry.get("timestamp", ""), ctx))

    if len(relevant) < 4:
        return 0.0

    mid = len(relevant) // 2
    first = Counter(ctx for _, ctx in relevant[:mid])
    second = Counter(ctx for _, ctx in relevant[mid:])
    all_ctx = set(first) | set(second)
    total_first = sum(first.values()) or 1
    total_second = sum(second.values()) or 1

    shift = 0.0
    for ctx in all_ctx:
        p1 = first.get(ctx, 0) / total_first
        p2 = second.get(ctx, 0) / total_second
        shift += abs(p1 - p2)
    return round(shift / 2, 3)


def _classify_taxonomy(
    flags: list[str],
    *,
    prod_occurrences: int,
    sim_prod_gap: float,
    baseline_prod: float,
) -> FalsePromotionClass:
    if "shadow_overconfidence" in flags:
        return "SIMULATION_BIAS"
    if "context_shift_mismatch" in flags:
        return "CONTEXT_SHIFT"
    if sim_prod_gap >= SCORE_GAP_OVERFIT:
        return "OVERFITTED_PROMOTION"
    if prod_occurrences <= 3 and baseline_prod < 0.7:
        return "PREMATURE_PROMOTION"
    if prod_occurrences <= 4:
        return "FREQUENCY_ILLUSION"
    if "post_promotion_failure" in flags:
        return "PREMATURE_PROMOTION"
    return "SIMULATION_BIAS"


def _severity_from_flags(flags: list[str], evidence: FalsePromotionEvidence) -> float:
    score = 0.0
    if "post_promotion_failure" in flags:
        score += 0.35 + (POST_PROMOTION_FAILURE_THRESHOLD - evidence.prod_success_rate) * 0.5
    if "unstable_generalization" in flags:
        score += 0.25 + evidence.stability_decay * 0.5
    if "context_shift_mismatch" in flags:
        score += 0.20 + evidence.context_shift_score * 0.3
    if "shadow_overconfidence" in flags:
        score += 0.30 + min(evidence.sim_prod_gap, 0.5)
    return round(min(1.0, score), 3)


def _resolve_action(
    severity: float,
    flags: list[str],
    current_status: LifecycleStatus,
) -> tuple[LifecycleStatus, LifecycleAction]:
    if severity < 0.45:
        if current_status == "degraded":
            return "degraded", "monitor"
        return current_status if current_status != "demoted" else "demoted", "maintain"

    if severity >= 0.85 and "post_promotion_failure" in flags:
        return "demoted", "demote"

    if severity >= 0.72:
        return "quarantined", "remove_from_fast_path"

    if severity >= 0.52 or current_status == "degraded":
        return "degraded", "remove_from_fast_path"

    return "degraded", "degrade"


def evaluate_promoted_entry(
    entry: PromotedLearning,
    *,
    shadow_row: FingerprintShadowComparison | None,
    prod_entries: list[dict[str, Any]],
) -> FalsePromotionFinding | None:
    if entry.status == "demoted":
        return None

    flags: list[str] = []
    evidence = FalsePromotionEvidence()

    prod_success = 0.5
    prod_occ = 0
    sim_prod_gap = 0.0
    current_stability = entry.stability
    shadow_class = "unknown"

    if shadow_row is not None:
        prod_success = shadow_row.production.success_rate
        prod_occ = shadow_row.production.occurrences
        sim_prod_gap = abs(
            (shadow_row.simulation.decayed_score or shadow_row.simulation.success_rate)
            - shadow_row.production.success_rate
        )
        current_stability = shadow_row.stability
        shadow_class = shadow_row.classification
        evidence.sim_prod_gap = round(sim_prod_gap, 3)
        evidence.shadow_classification = shadow_class

    evidence.prod_success_rate = prod_success
    evidence.prod_occurrences = prod_occ
    evidence.stability_current = current_stability
    evidence.prod_drop = round(max(0.0, entry.baseline_prod_score - prod_success), 3)
    evidence.stability_decay = round(max(0.0, entry.baseline_stability - current_stability), 3)

    if prod_occ >= MIN_POST_PROMOTION_OBS and prod_success < POST_PROMOTION_FAILURE_THRESHOLD:
        flags.append("post_promotion_failure")

    if evidence.stability_decay >= STABILITY_COLLAPSE_DELTA:
        flags.append("unstable_generalization")

    ctx_shift = _context_shift_score(prod_entries, entry.fp_id)
    evidence.context_shift_score = ctx_shift
    if ctx_shift >= CONTEXT_SHIFT_THRESHOLD:
        flags.append("context_shift_mismatch")

    if shadow_row is not None and shadow_class != "validated":
        flags.append("shadow_overconfidence")

    if not flags:
        return None

    taxonomy = _classify_taxonomy(
        flags,
        prod_occurrences=prod_occ,
        sim_prod_gap=sim_prod_gap,
        baseline_prod=entry.baseline_prod_score,
    )
    severity = _severity_from_flags(flags, evidence)
    new_status, action = _resolve_action(severity, flags, entry.status)
    primary_reason = flags[0]

    return FalsePromotionFinding(
        fp_id=entry.fp_id,
        patch_id=entry.patch_id,
        status=new_status,
        reason=primary_reason,
        false_promotion_class=taxonomy,
        severity=severity,
        action=action,
        flags=flags,
        evidence=evidence,
        previous_status=entry.status,
    )


class FalsePromotionDetector:
    """Post-promotion monitor — only evaluates entries in promoted_learnings.json."""

    def __init__(
        self,
        store: PromotedLearningStore | None = None,
        *,
        comparator: ShadowComparator | None = None,
        audit_path: Path | None = None,
    ):
        self.store = store or PromotedLearningStore()
        self.comparator = comparator or ShadowComparator()
        self.audit_path = audit_path or DEFAULT_AUDIT_PATH

    def evaluate_entry(self, entry: PromotedLearning) -> FalsePromotionFinding | None:
        shadow = self.comparator.build_report()
        shadow_by_fp = {row.fp_id: row for row in shadow.comparisons}
        prod_entries = load_production_entries(self.comparator.ingest_path)
        return evaluate_promoted_entry(
            entry,
            shadow_row=shadow_by_fp.get(entry.fp_id),
            prod_entries=prod_entries,
        )

    def run(self, *, persist: bool = False) -> FalsePromotionReport:
        shadow = self.comparator.build_report()
        shadow_by_fp = {row.fp_id: row for row in shadow.comparisons}
        prod_entries = load_production_entries(self.comparator.ingest_path)

        findings: list[FalsePromotionFinding] = []
        for entry in self.store.promoted_entries():
            finding = evaluate_promoted_entry(
                entry,
                shadow_row=shadow_by_fp.get(entry.fp_id),
                prod_entries=prod_entries,
            )
            if finding is not None:
                findings.append(finding)

        degraded = quarantined = demoted = 0
        if persist:
            for finding in findings:
                if finding.status != finding.previous_status:
                    if finding.status == "degraded":
                        degraded += 1
                    elif finding.status == "quarantined":
                        quarantined += 1
                    elif finding.status == "demoted":
                        demoted += 1
                self.store.apply_lifecycle_update(
                    finding.fp_id,
                    finding.patch_id,
                    status=finding.status,
                    false_promotion_class=finding.false_promotion_class,
                    monitoring_flags=finding.flags,
                    stability=finding.evidence.stability_current,
                )
            if findings:
                self.store.save()
                self._append_audit(findings)

        total_promotions, false_promotions, fpr = _compute_fpr(self.store, self.audit_path)

        report = FalsePromotionReport(
            findings=findings,
            evaluated=len(self.store.promoted_entries()),
            flagged=len(findings),
            degraded_count=degraded if persist else sum(1 for f in findings if f.status == "degraded"),
            quarantined_count=quarantined if persist else sum(1 for f in findings if f.status == "quarantined"),
            demoted_count=demoted if persist else sum(1 for f in findings if f.status == "demoted"),
            false_promotion_rate=fpr,
            total_promotions=total_promotions,
            false_promotions=false_promotions,
        )
        report.debug_trace = format_false_promotion_trace(report)
        return report

    def _append_audit(self, findings: list[FalsePromotionFinding]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict[str, Any]] = []
        if self.audit_path.exists():
            raw = json.loads(self.audit_path.read_text(encoding="utf-8"))
            existing = list(raw.get("events", []))
        now = datetime.now(timezone.utc).isoformat()
        for finding in findings:
            existing.append({"timestamp": now, **finding.to_dict()})
        payload = {
            "detector_version": DETECTOR_VERSION,
            "events": existing[-500:],
        }
        self.audit_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _compute_fpr(
    store: PromotedLearningStore,
    audit_path: Path,
) -> tuple[int, int, float | None]:
    total = len(store.entries)
    if total == 0:
        return 0, 0, None

    false_count = sum(
        1 for e in store.entries.values() if e.status in ("quarantined", "demoted")
    )
    if audit_path.exists():
        raw = json.loads(audit_path.read_text(encoding="utf-8"))
        audited_fps = {
            (ev["fp_id"], ev["patch_id"])
            for ev in raw.get("events", [])
            if ev.get("status") in ("quarantined", "demoted")
        }
        false_count = max(false_count, len(audited_fps))

    fpr = round(false_count / total, 3) if total else None
    return total, false_count, fpr


def format_false_promotion_trace(report: FalsePromotionReport) -> str:
    lines = [
        "=== False Promotion Detector | post-promotion truth pressure (v1) ===",
        f"  evaluated: {report.evaluated} | flagged: {report.flagged}",
        f"  lifecycle: degraded={report.degraded_count} quarantined={report.quarantined_count} "
        f"demoted={report.demoted_count}",
    ]
    if report.false_promotion_rate is not None:
        lines.append(
            f"  FPR (false promotion rate): {report.false_promotion_rate:.1%} "
            f"({report.false_promotions}/{report.total_promotions})"
        )
    else:
        lines.append("  FPR: unknown (no promotions yet)")

    if not report.findings:
        lines.append("\n  No false promotion signals — promoted set holding.")
        return "\n".join(lines)

    lines.append("\n  Findings:")
    for f in report.findings:
        lines.append(
            f"\n  [{f.status.upper()}] {f.fp_id} -> {f.patch_id} "
            f"class={f.false_promotion_class} severity={f.severity:.2f}"
        )
        lines.append(f"    reason: {f.reason} | action: {f.action}")
        lines.append(f"    flags: {', '.join(f.flags)}")
        ev = f.evidence
        lines.append(
            f"    evidence: prod={ev.prod_success_rate:.2f} drop={ev.prod_drop:.2f} "
            f"gap={ev.sim_prod_gap:.2f} stability_decay={ev.stability_decay:.2f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="False promotion detector — post-promotion monitor")
    parser.add_argument("--persist", action="store_true", help="Apply lifecycle updates to promoted store")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--learning", type=Path, default=None)
    parser.add_argument("--ingest", type=Path, default=None)
    args = parser.parse_args(argv)

    comparator = ShadowComparator(
        learning_path=args.learning,
        ingest_path=args.ingest,
    )
    detector = FalsePromotionDetector(
        PromotedLearningStore(args.store),
        comparator=comparator,
    )
    report = detector.run(persist=args.persist)

    if args.json:
        payload = report.to_dict()
        payload["trace"] = report.debug_trace
        print(json.dumps(payload, indent=2))
    else:
        print(report.debug_trace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
