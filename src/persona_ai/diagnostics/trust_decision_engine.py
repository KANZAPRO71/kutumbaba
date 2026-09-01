"""Trust Decision Engine v1 — drift-to-demotion decision compression layer.

Converts continuous drift warnings into governed lifecycle recommendations.
Does NOT auto-demote; QUARANTINE_REVIEW requires explicit --apply-quarantine.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from persona_ai.diagnostics.false_promotion_detector import FalsePromotionDetector
from persona_ai.diagnostics.promotion_gate import (
    DEFAULT_STORE_PATH,
    PromotedLearningStore,
)
from persona_ai.diagnostics.shadow_comparator import ShadowComparator, load_production_entries
from persona_ai.diagnostics.shadow_drift_alerts import (
    DEFAULT_ALERTS_PATH,
    DEFAULT_WINDOW_SESSIONS,
    DriftAlert,
    ShadowDriftMonitor,
    _fp_observations,
)

DECISION_VERSION = "v1"
DEFAULT_DECISIONS_PATH = Path(".persona_ai/trust_decisions.json")

ESCALATION_MIN_STREAK = 3
ESCALATION_MIN_SEVERITY = 0.6
STRUCTURAL_PROD_TREND = -0.25
STRUCTURAL_GAP_WIDENING = 0.20
HIGH_VARIANCE_THRESHOLD = 0.35
RECOVERY_STABILITY_REBOUND = 0.05
VOLATILITY_SEVERITY_FLOOR = 0.5

DecisionRecommendation = Literal[
    "MAINTAIN",
    "MONITOR_EXTEND",
    "QUARANTINE_REVIEW",
    "DEMOTION_RECOMMENDATION",
    "RECOVERY_STABLE",
]

DecisionState = Literal[
    "NO_ACTION",
    "ESCALATION_CANDIDATE",
    "VOLATILITY_HOLD",
    "DEMOTION_CANDIDATE",
    "RECOVERING",
]


@dataclass
class TrustDecision:
    fp_id: str
    patch_id: str
    drift_state: str
    decision_state: DecisionState
    recommendation: DecisionRecommendation
    confidence: float
    reasons: list[str]
    at_risk_streak: int = 0
    drift_severity: float = 0.0
    prod_trend_delta: float = 0.0
    gap_widening: float = 0.0
    prod_success_variance: float = 0.0
    false_promotion_overlap: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrustDecisionReport:
    decisions: list[TrustDecision]
    evaluated: int
    action_required: int
    quarantine_candidates: int
    demotion_candidates: int
    recovery_count: int
    debug_trace: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_version": DECISION_VERSION,
            "evaluated": self.evaluated,
            "action_required": self.action_required,
            "quarantine_candidates": self.quarantine_candidates,
            "demotion_candidates": self.demotion_candidates,
            "recovery_count": self.recovery_count,
            "decisions": [d.to_dict() for d in self.decisions],
        }


def load_drift_snapshots(alerts_path: Path | None = None) -> list[dict[str, Any]]:
    path = alerts_path or DEFAULT_ALERTS_PATH
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return list(raw.get("snapshots", []))


def compute_at_risk_streak(
    snapshots: list[dict[str, Any]],
    fp_id: str,
    patch_id: str,
) -> tuple[int, int]:
    """Return (current_streak, prior_streak) from persisted drift snapshots."""
    streaks: list[int] = []
    current = 0
    for snap in snapshots:
        snap_streak = 0
        for alert in snap.get("alerts", []):
            if alert.get("fp_id") == fp_id and alert.get("patch_id") == patch_id:
                if alert.get("alert_status") == "at_risk":
                    snap_streak = 1
                break
        if snap_streak:
            current += 1
        else:
            if current:
                streaks.append(current)
            current = 0
    if current:
        streaks.append(current)

    if not streaks:
        return 0, 0
    if len(streaks) == 1:
        return streaks[0], 0
    return streaks[-1], streaks[-2]


def compute_prod_success_variance(
    prod_entries: list[dict[str, Any]],
    fp_id: str,
    *,
    window: int = DEFAULT_WINDOW_SESSIONS,
) -> float:
    obs = _fp_observations(prod_entries, fp_id, window=window)
    if len(obs) < 2:
        return 0.0
    values = [o["success"] for o in obs]
    return round(statistics.pstdev(values), 3)


def _confidence(
    *,
    severity: float,
    streak: int,
    structural: bool,
    overlap: bool,
) -> float:
    base = severity * 0.5
    if structural:
        base += 0.25
    if streak >= ESCALATION_MIN_STREAK:
        base += 0.15
    if overlap:
        base += 0.10
    return round(min(0.99, max(0.1, base)), 3)


def evaluate_trust_decision(
    alert: DriftAlert,
    *,
    at_risk_streak: int,
    prior_at_risk_streak: int,
    false_promotion_flagged: bool,
    prod_variance: float,
) -> TrustDecision:
    """Apply v1 decision rules to one drift alert."""
    sig = alert.signals
    reasons: list[str] = []
    drift_state = alert.alert_status.upper()

    # Rule 4: Recovery — streak decreasing + stability rebound
    if (
        alert.alert_status in ("stable", "watch")
        and prior_at_risk_streak > at_risk_streak
        and sig.stability_derivative >= RECOVERY_STABILITY_REBOUND
    ):
        reasons.extend([
            f"at_risk_streak_declining: {prior_at_risk_streak} -> {at_risk_streak}",
            f"stability_rebound: {sig.stability_derivative:+.2f}",
        ])
        return TrustDecision(
            fp_id=alert.fp_id,
            patch_id=alert.patch_id,
            drift_state=drift_state,
            decision_state="RECOVERING",
            recommendation="RECOVERY_STABLE",
            confidence=_confidence(severity=alert.severity, streak=at_risk_streak, structural=False, overlap=False),
            reasons=reasons,
            at_risk_streak=at_risk_streak,
            drift_severity=alert.severity,
            prod_trend_delta=sig.prod_trend_delta,
            gap_widening=sig.gap_widening,
            prod_success_variance=prod_variance,
            false_promotion_overlap=false_promotion_flagged,
        )

    # Rule 3: Structural degradation
    if sig.prod_trend_delta <= STRUCTURAL_PROD_TREND and sig.gap_widening >= STRUCTURAL_GAP_WIDENING:
        reasons.extend([
            f"prod_trend: {sig.prod_trend_delta:+.2f}",
            f"gap_widening: {sig.gap_widening:+.2f}",
        ])
        if false_promotion_flagged:
            reasons.append("false_promotion_detector_confirms")
        return TrustDecision(
            fp_id=alert.fp_id,
            patch_id=alert.patch_id,
            drift_state=drift_state,
            decision_state="DEMOTION_CANDIDATE",
            recommendation="DEMOTION_RECOMMENDATION",
            confidence=_confidence(
                severity=alert.severity,
                streak=at_risk_streak,
                structural=True,
                overlap=false_promotion_flagged,
            ),
            reasons=reasons,
            at_risk_streak=at_risk_streak,
            drift_severity=alert.severity,
            prod_trend_delta=sig.prod_trend_delta,
            gap_widening=sig.gap_widening,
            prod_success_variance=prod_variance,
            false_promotion_overlap=false_promotion_flagged,
        )

    # Rule 2: Volatility shield (blocks escalation)
    volatility_shield = (
        alert.severity >= VOLATILITY_SEVERITY_FLOOR
        and not false_promotion_flagged
        and prod_variance >= HIGH_VARIANCE_THRESHOLD
    )
    if volatility_shield:
        reasons.extend([
            f"drift_severity: {alert.severity:.2f}",
            f"prod_variance: {prod_variance:.2f} (high — likely noise)",
            "false_promotion_detector: clean",
        ])
        return TrustDecision(
            fp_id=alert.fp_id,
            patch_id=alert.patch_id,
            drift_state=drift_state,
            decision_state="VOLATILITY_HOLD",
            recommendation="MONITOR_EXTEND",
            confidence=_confidence(severity=alert.severity * 0.6, streak=at_risk_streak, structural=False, overlap=False),
            reasons=reasons,
            at_risk_streak=at_risk_streak,
            drift_severity=alert.severity,
            prod_trend_delta=sig.prod_trend_delta,
            gap_widening=sig.gap_widening,
            prod_success_variance=prod_variance,
            false_promotion_overlap=false_promotion_flagged,
        )

    # Rule 1: Escalation to quarantine review
    effective_streak = at_risk_streak
    if alert.alert_status == "at_risk":
        effective_streak = max(at_risk_streak, 1)

    if (
        effective_streak >= ESCALATION_MIN_STREAK
        and alert.severity >= ESCALATION_MIN_SEVERITY
        and alert.alert_status == "at_risk"
    ):
        reasons.extend([
            f"at_risk_streak: {effective_streak}",
            f"drift_severity: {alert.severity:.2f}",
            f"prod_trend: {sig.prod_trend_delta:+.2f}",
        ])
        return TrustDecision(
            fp_id=alert.fp_id,
            patch_id=alert.patch_id,
            drift_state=f"{drift_state} -> ESCALATION_CANDIDATE",
            decision_state="ESCALATION_CANDIDATE",
            recommendation="QUARANTINE_REVIEW",
            confidence=_confidence(
                severity=alert.severity,
                streak=effective_streak,
                structural=False,
                overlap=false_promotion_flagged,
            ),
            reasons=reasons,
            at_risk_streak=effective_streak,
            drift_severity=alert.severity,
            prod_trend_delta=sig.prod_trend_delta,
            gap_widening=sig.gap_widening,
            prod_success_variance=prod_variance,
            false_promotion_overlap=false_promotion_flagged,
        )

    # Default: maintain / extend monitoring for watch-level drift
    if alert.alert_status == "watch":
        reasons.append(f"watch-level drift severity={alert.severity:.2f}")
        return TrustDecision(
            fp_id=alert.fp_id,
            patch_id=alert.patch_id,
            drift_state=drift_state,
            decision_state="NO_ACTION",
            recommendation="MONITOR_EXTEND",
            confidence=_confidence(severity=alert.severity * 0.5, streak=at_risk_streak, structural=False, overlap=False),
            reasons=reasons,
            at_risk_streak=at_risk_streak,
            drift_severity=alert.severity,
            prod_trend_delta=sig.prod_trend_delta,
            gap_widening=sig.gap_widening,
            prod_success_variance=prod_variance,
            false_promotion_overlap=false_promotion_flagged,
        )

    return TrustDecision(
        fp_id=alert.fp_id,
        patch_id=alert.patch_id,
        drift_state=drift_state,
        decision_state="NO_ACTION",
        recommendation="MAINTAIN",
        confidence=0.5,
        reasons=["no decision trigger"],
        at_risk_streak=at_risk_streak,
        drift_severity=alert.severity,
        prod_trend_delta=sig.prod_trend_delta,
        gap_widening=sig.gap_widening,
        prod_success_variance=prod_variance,
        false_promotion_overlap=false_promotion_flagged,
    )


class TrustDecisionEngine:
    """State transition policy engine: warning -> governed decision."""

    def __init__(
        self,
        store: PromotedLearningStore | None = None,
        *,
        comparator: ShadowComparator | None = None,
        alerts_path: Path | None = None,
        decisions_path: Path | None = None,
    ):
        self.store = store or PromotedLearningStore()
        self.comparator = comparator or ShadowComparator()
        self.alerts_path = alerts_path or DEFAULT_ALERTS_PATH
        self.decisions_path = decisions_path or DEFAULT_DECISIONS_PATH

    def run(
        self,
        *,
        persist: bool = False,
        apply_quarantine: bool = False,
    ) -> TrustDecisionReport:
        drift_monitor = ShadowDriftMonitor(
            self.store,
            comparator=self.comparator,
            alerts_path=self.alerts_path,
        )
        drift_report = drift_monitor.run(persist=False)

        fp_detector = FalsePromotionDetector(self.store, comparator=self.comparator)
        fp_report = fp_detector.run(persist=False)
        fp_by_key = {
            (f.fp_id, f.patch_id): f
            for f in fp_report.findings
        }

        snapshots = load_drift_snapshots(self.alerts_path)
        prod_entries = load_production_entries(self.comparator.ingest_path)

        decisions: list[TrustDecision] = []
        for alert in drift_report.alerts:
            if alert.previous_status == "demoted":
                continue
            streak, prior_streak = compute_at_risk_streak(
                snapshots, alert.fp_id, alert.patch_id
            )
            if alert.alert_status == "at_risk":
                streak = max(streak + 1, 1)

            fp_flagged = (alert.fp_id, alert.patch_id) in fp_by_key
            variance = compute_prod_success_variance(prod_entries, alert.fp_id)

            decision = evaluate_trust_decision(
                alert,
                at_risk_streak=streak,
                prior_at_risk_streak=prior_streak,
                false_promotion_flagged=fp_flagged,
                prod_variance=variance,
            )
            decisions.append(decision)

        quarantine_candidates = sum(
            1 for d in decisions if d.recommendation == "QUARANTINE_REVIEW"
        )
        demotion_candidates = sum(
            1 for d in decisions if d.recommendation == "DEMOTION_RECOMMENDATION"
        )
        recovery_count = sum(1 for d in decisions if d.recommendation == "RECOVERY_STABLE")
        action_required = sum(
            1 for d in decisions
            if d.recommendation not in ("MAINTAIN", "MONITOR_EXTEND")
        )

        if apply_quarantine:
            for decision in decisions:
                if decision.recommendation == "QUARANTINE_REVIEW":
                    self.store.apply_lifecycle_update(
                        decision.fp_id,
                        decision.patch_id,
                        status="quarantined",
                        false_promotion_class="DRIFT_ESCALATION",
                        monitoring_flags=decision.reasons,
                    )
            if quarantine_candidates:
                self.store.save()

        if persist:
            self._persist_decisions(decisions)

        report = TrustDecisionReport(
            decisions=decisions,
            evaluated=len(decisions),
            action_required=action_required,
            quarantine_candidates=quarantine_candidates,
            demotion_candidates=demotion_candidates,
            recovery_count=recovery_count,
        )
        report.debug_trace = format_decision_trace(report, apply_quarantine=apply_quarantine)
        return report

    def _persist_decisions(self, decisions: list[TrustDecision]) -> None:
        self.decisions_path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict[str, Any]] = []
        if self.decisions_path.exists():
            raw = json.loads(self.decisions_path.read_text(encoding="utf-8"))
            existing = list(raw.get("history", []))

        now = datetime.now(timezone.utc).isoformat()
        existing.append(
            {
                "timestamp": now,
                "decisions": [d.to_dict() for d in decisions if d.recommendation != "MAINTAIN"],
            }
        )
        payload = {
            "decision_version": DECISION_VERSION,
            "history": existing[-100:],
        }
        self.decisions_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def format_decision_trace(
    report: TrustDecisionReport,
    *,
    apply_quarantine: bool = False,
) -> str:
    lines = [
        "=== Trust Decision Engine | drift-to-demotion policy (v1) ===",
        f"  evaluated: {report.evaluated} | action_required: {report.action_required}",
        f"  quarantine_candidates: {report.quarantine_candidates} | "
        f"demotion_candidates: {report.demotion_candidates} | "
        f"recovery: {report.recovery_count}",
        "  recommendations only — use --apply-quarantine for QUARANTINE_REVIEW",
    ]
    if apply_quarantine and report.quarantine_candidates:
        lines.append(f"  APPLIED: {report.quarantine_candidates} quarantine transition(s)")

    actionable = [
        d for d in report.decisions
        if d.recommendation not in ("MAINTAIN",)
    ]
    if not actionable:
        lines.append("\n  No trust decisions required — all patterns within bounds.")
        return "\n".join(lines)

    lines.append("\n  Decision signals:")
    for d in sorted(actionable, key=lambda x: -x.confidence):
        lines.append(f"\n  DECISION [{d.fp_id}] state={d.drift_state}")
        lines.append(
            f"    patch={d.patch_id} -> {d.recommendation} "
            f"(confidence={d.confidence:.2f})"
        )
        lines.append(f"    decision_state: {d.decision_state}")
        lines.append(f"    reasons:")
        for reason in d.reasons:
            lines.append(f"      - {reason}")
        if d.at_risk_streak:
            lines.append(
                f"    metrics: streak={d.at_risk_streak} severity={d.drift_severity:.2f} "
                f"prod_trend={d.prod_trend_delta:+.2f} variance={d.prod_success_variance:.2f}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Trust decision engine — drift-to-demotion policy")
    parser.add_argument("--persist", action="store_true", help="Append to trust_decisions.json")
    parser.add_argument(
        "--apply-quarantine",
        action="store_true",
        help="Apply QUARANTINE_REVIEW recommendations to promoted store",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--learning", type=Path, default=None)
    parser.add_argument("--ingest", type=Path, default=None)
    args = parser.parse_args(argv)

    comparator = ShadowComparator(
        learning_path=args.learning,
        ingest_path=args.ingest,
    )
    engine = TrustDecisionEngine(
        PromotedLearningStore(args.store),
        comparator=comparator,
    )
    report = engine.run(persist=args.persist, apply_quarantine=args.apply_quarantine)

    if args.json:
        payload = report.to_dict()
        payload["trace"] = report.debug_trace
        print(json.dumps(payload, indent=2))
    else:
        print(report.debug_trace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
