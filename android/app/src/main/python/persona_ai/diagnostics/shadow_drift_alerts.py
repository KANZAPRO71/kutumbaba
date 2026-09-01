"""Shadow Drift Alerts v1 — continuous trust degradation early warning.

Monitors promoted set for slow poison (trend-based) before false promotion triggers.
Read-only by default; optional --persist-drift updates elasticity_weight on promoted store.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from persona_ai.diagnostics.promotion_gate import (
    DEFAULT_STORE_PATH,
    PromotedLearning,
    PromotedLearningStore,
)
from persona_ai.diagnostics.shadow_comparator import (
    FingerprintShadowComparison,
    ShadowComparator,
    load_production_entries,
)

DRIFT_VERSION = "v1"
DEFAULT_ALERTS_PATH = Path(".persona_ai/drift_alerts.json")

DEFAULT_WINDOW_SESSIONS = 5
MIN_WINDOW_OBS = 3

PROD_TREND_ALERT = -0.15
GAP_WIDENING_ALERT = 0.12
STABILITY_DERIVATIVE_ALERT = -0.10
CONTEXT_ENTROPY_SHIFT_ALERT = 0.25
STRONG_PROD_DROP = 0.20

DriftClassification = Literal[
    "STABLE",
    "EARLY_DEGRADATION",
    "GAP_WIDENING",
    "CONTEXT_DRIFT",
    "STABILITY_EROSION",
    "COMPOUND_DRIFT",
]

TrustAlertStatus = Literal["stable", "watch", "at_risk"]


@dataclass
class DriftSignals:
    prod_success_early: float = 0.0
    prod_success_late: float = 0.0
    prod_trend_delta: float = 0.0
    shadow_gap_early: float = 0.0
    shadow_gap_late: float = 0.0
    gap_widening: float = 0.0
    stability_current: float = 0.0
    stability_derivative: float = 0.0
    context_entropy_early: float = 0.0
    context_entropy_late: float = 0.0
    context_entropy_shift: float = 0.0
    window_observations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def active_flags(self) -> list[str]:
        flags: list[str] = []
        if self.prod_trend_delta <= PROD_TREND_ALERT:
            flags.append("prod_success_declining")
        if self.gap_widening >= GAP_WIDENING_ALERT:
            flags.append("sim_prod_gap_widening")
        if self.stability_derivative <= STABILITY_DERIVATIVE_ALERT:
            flags.append("stability_erosion")
        if self.context_entropy_shift >= CONTEXT_ENTROPY_SHIFT_ALERT:
            flags.append("context_entropy_rising")
        return flags


@dataclass
class RecommendedAction:
    action: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DriftAlert:
    fp_id: str
    patch_id: str
    previous_status: str
    alert_status: TrustAlertStatus
    classification: DriftClassification
    severity: float
    elasticity_weight: float
    signals: DriftSignals
    flags: list[str]
    recommended_actions: list[RecommendedAction]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fp_id": self.fp_id,
            "patch_id": self.patch_id,
            "previous_status": self.previous_status,
            "alert_status": self.alert_status,
            "classification": self.classification,
            "severity": self.severity,
            "elasticity_weight": self.elasticity_weight,
            "signals": self.signals.to_dict(),
            "flags": self.flags,
            "recommended_actions": [a.to_dict() for a in self.recommended_actions],
        }


@dataclass
class TrustTimelineEvent:
    timestamp: str
    fp_id: str
    patch_id: str
    event_type: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DriftAlertReport:
    alerts: list[DriftAlert]
    stable_count: int
    watch_count: int
    at_risk_count: int
    evaluated: int
    timeline: list[TrustTimelineEvent] = field(default_factory=list)
    debug_trace: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "drift_version": DRIFT_VERSION,
            "evaluated": self.evaluated,
            "stable_count": self.stable_count,
            "watch_count": self.watch_count,
            "at_risk_count": self.at_risk_count,
            "alerts": [a.to_dict() for a in self.alerts],
            "timeline": [t.to_dict() for t in self.timeline],
        }


def _entropy(counts: Counter[str]) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return round(entropy, 3)


def _outcome_success(outcome: str) -> float:
    if outcome in ("observed_success", "partial_success"):
        return 1.0
    if outcome == "degraded":
        return 0.5
    return 0.0


def _fp_observations(
    entries: list[dict[str, Any]],
    fp_id: str,
    *,
    window: int,
) -> list[dict[str, Any]]:
    obs: list[dict[str, Any]] = []
    for entry in entries:
        ctx = entry.get("context", "unknown") or "unknown"
        ts = entry.get("timestamp", "")
        sid = entry.get("session_id", "")
        for fp in entry.get("fingerprints", []):
            if fp.get("fp_id") == fp_id:
                obs.append(
                    {
                        "timestamp": ts,
                        "session_id": sid,
                        "context": ctx,
                        "outcome": fp.get("outcome", "observed"),
                        "success": _outcome_success(fp.get("outcome", "observed")),
                    }
                )
    if len(obs) > window:
        obs = obs[-window:]
    return obs


def compute_drift_signals(
    entry: PromotedLearning,
    *,
    shadow_row: FingerprintShadowComparison | None,
    prod_entries: list[dict[str, Any]],
    window: int = DEFAULT_WINDOW_SESSIONS,
) -> DriftSignals:
    """Aggregate drift signals for one promoted (fp_id, patch_id) pair."""
    obs = _fp_observations(prod_entries, entry.fp_id, window=window)
    signals = DriftSignals(window_observations=len(obs))

    sim_rate = entry.baseline_sim_score
    if shadow_row is not None:
        sim_rate = shadow_row.simulation.decayed_score or shadow_row.simulation.success_rate
        signals.stability_current = shadow_row.stability
    else:
        signals.stability_current = entry.stability

    signals.stability_derivative = round(
        signals.stability_current - entry.baseline_stability, 3
    )

    if len(obs) < MIN_WINDOW_OBS:
        return signals

    mid = len(obs) // 2
    early, late = obs[:mid], obs[mid:]
    if not early or not late:
        return signals

    early_success = sum(o["success"] for o in early) / len(early)
    late_success = sum(o["success"] for o in late) / len(late)
    signals.prod_success_early = round(early_success, 3)
    signals.prod_success_late = round(late_success, 3)
    signals.prod_trend_delta = round(late_success - early_success, 3)

    signals.shadow_gap_early = round(sim_rate - early_success, 3)
    signals.shadow_gap_late = round(sim_rate - late_success, 3)
    signals.gap_widening = round(signals.shadow_gap_late - signals.shadow_gap_early, 3)

    early_ctx = Counter(o["context"] for o in early)
    late_ctx = Counter(o["context"] for o in late)
    signals.context_entropy_early = _entropy(early_ctx)
    signals.context_entropy_late = _entropy(late_ctx)
    signals.context_entropy_shift = round(
        abs(signals.context_entropy_late - signals.context_entropy_early), 3
    )

    return signals


def _severity_from_signals(signals: DriftSignals, flags: list[str]) -> float:
    score = 0.0
    if "prod_success_declining" in flags:
        score += min(0.45, abs(signals.prod_trend_delta) * 1.5)
    if "sim_prod_gap_widening" in flags:
        score += min(0.35, signals.gap_widening * 1.2)
    if "stability_erosion" in flags:
        score += min(0.30, abs(signals.stability_derivative) * 1.2)
    if "context_entropy_rising" in flags:
        score += min(0.25, signals.context_entropy_shift * 0.8)
    if signals.prod_trend_delta <= -STRONG_PROD_DROP:
        score += 0.15
    return round(min(1.0, score), 3)


def _classify_drift(flags: list[str]) -> DriftClassification:
    if len(flags) >= 2:
        return "COMPOUND_DRIFT"
    if not flags:
        return "STABLE"
    mapping = {
        "prod_success_declining": "EARLY_DEGRADATION",
        "sim_prod_gap_widening": "GAP_WIDENING",
        "context_entropy_rising": "CONTEXT_DRIFT",
        "stability_erosion": "STABILITY_EROSION",
    }
    return mapping.get(flags[0], "COMPOUND_DRIFT")


def _alert_status(severity: float, flags: list[str], signals: DriftSignals) -> TrustAlertStatus:
    strong_single = (
        signals.prod_trend_delta <= -STRONG_PROD_DROP
        or signals.gap_widening >= GAP_WIDENING_ALERT * 1.5
    )
    if severity >= 0.55 or len(flags) >= 2 or strong_single:
        return "at_risk"
    if severity >= 0.30 or flags:
        return "watch"
    return "stable"


def _recommended_actions(
    alert_status: TrustAlertStatus,
    severity: float,
    classification: DriftClassification,
) -> list[RecommendedAction]:
    actions: list[RecommendedAction] = []
    if alert_status == "stable":
        return actions

    weight = round(max(0.2, 1.0 - severity * 0.8), 2)
    actions.append(
        RecommendedAction(
            action="reduce_fast_path_weight",
            detail=f"suggested elasticity_weight={weight} (enforced via elasticity_enforcement)",
        )
    )
    actions.append(
        RecommendedAction(
            action="increase_monitoring",
            detail="run drift + false promotion detector each ingest batch",
        )
    )
    if alert_status == "at_risk":
        actions.append(
            RecommendedAction(
                action="pre_emptive_quarantine_review",
                detail=f"classification={classification} — review before demotion trigger",
            )
        )
    return actions


def evaluate_drift(
    entry: PromotedLearning,
    *,
    shadow_row: FingerprintShadowComparison | None,
    prod_entries: list[dict[str, Any]],
    window: int = DEFAULT_WINDOW_SESSIONS,
) -> DriftAlert:
    """Evaluate drift for one promoted entry; always returns an alert row."""
    signals = compute_drift_signals(
        entry,
        shadow_row=shadow_row,
        prod_entries=prod_entries,
        window=window,
    )
    flags = signals.active_flags()
    severity = _severity_from_signals(signals, flags) if flags else 0.0
    classification = _classify_drift(flags) if flags else "STABLE"
    alert_status = _alert_status(severity, flags, signals)
    elasticity = round(max(0.2, 1.0 - severity * 0.8), 3)

    return DriftAlert(
        fp_id=entry.fp_id,
        patch_id=entry.patch_id,
        previous_status=entry.status,
        alert_status=alert_status,
        classification=classification,
        severity=severity,
        elasticity_weight=elasticity,
        signals=signals,
        flags=flags,
        recommended_actions=_recommended_actions(alert_status, severity, classification),
    )


def build_trust_timeline(
    store: PromotedLearningStore,
    *,
    alerts_path: Path | None = None,
    audit_path: Path | None = None,
) -> list[TrustTimelineEvent]:
    """Unified lifecycle view: promotion, drift, demotion events."""
    from persona_ai.diagnostics.false_promotion_detector import DEFAULT_AUDIT_PATH

    events: list[TrustTimelineEvent] = []

    for entry in store.promoted_entries():
        events.append(
            TrustTimelineEvent(
                timestamp=entry.first_promoted,
                fp_id=entry.fp_id,
                patch_id=entry.patch_id,
                event_type="promoted",
                detail=f"baseline prod={entry.baseline_prod_score:.2f} stability={entry.baseline_stability:.2f}",
            )
        )
        if entry.last_status_change and entry.last_status_change != entry.first_promoted:
            if entry.status in ("degraded", "quarantined", "demoted"):
                events.append(
                    TrustTimelineEvent(
                        timestamp=entry.last_status_change,
                        fp_id=entry.fp_id,
                        patch_id=entry.patch_id,
                        event_type=entry.status,
                        detail=entry.false_promotion_class or entry.status,
                    )
                )

    path = alerts_path or DEFAULT_ALERTS_PATH
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        for snap in raw.get("snapshots", [])[-20:]:
            ts = snap.get("timestamp", "")
            for alert in snap.get("alerts", []):
                if alert.get("alert_status") in ("watch", "at_risk"):
                    events.append(
                        TrustTimelineEvent(
                            timestamp=ts,
                            fp_id=alert["fp_id"],
                            patch_id=alert["patch_id"],
                            event_type=f"drift_{alert['alert_status']}",
                            detail=alert.get("classification", ""),
                        )
                    )

    audit = audit_path or DEFAULT_AUDIT_PATH
    if audit.exists():
        raw = json.loads(audit.read_text(encoding="utf-8"))
        for ev in raw.get("events", [])[-30:]:
            events.append(
                TrustTimelineEvent(
                    timestamp=ev.get("timestamp", ""),
                    fp_id=ev["fp_id"],
                    patch_id=ev["patch_id"],
                    event_type="false_promotion",
                    detail=f"{ev.get('status')} {ev.get('false_promotion_class', '')}",
                )
            )

    events.sort(key=lambda e: e.timestamp)
    return events


class ShadowDriftMonitor:
    """Continuous drift monitor for promoted trust set."""

    def __init__(
        self,
        store: PromotedLearningStore | None = None,
        *,
        comparator: ShadowComparator | None = None,
        alerts_path: Path | None = None,
        window: int = DEFAULT_WINDOW_SESSIONS,
    ):
        self.store = store or PromotedLearningStore()
        self.comparator = comparator or ShadowComparator()
        self.alerts_path = alerts_path or DEFAULT_ALERTS_PATH
        self.window = window

    def run(self, *, persist: bool = False) -> DriftAlertReport:
        shadow = self.comparator.build_report()
        shadow_by_fp = {row.fp_id: row for row in shadow.comparisons}
        prod_entries = load_production_entries(self.comparator.ingest_path)

        alerts: list[DriftAlert] = []
        for entry in self.store.promoted_entries():
            if entry.status == "demoted":
                continue
            alert = evaluate_drift(
                entry,
                shadow_row=shadow_by_fp.get(entry.fp_id),
                prod_entries=prod_entries,
                window=self.window,
            )
            alerts.append(alert)

        stable = sum(1 for a in alerts if a.alert_status == "stable")
        watch = sum(1 for a in alerts if a.alert_status == "watch")
        at_risk = sum(1 for a in alerts if a.alert_status == "at_risk")

        if persist:
            self._persist_snapshot(alerts)
            for alert in alerts:
                if alert.alert_status != "stable":
                    promoted = self.store.get(alert.fp_id, alert.patch_id)
                    if promoted is not None:
                        promoted.monitoring_flags = list(
                            set(promoted.monitoring_flags) | set(alert.flags)
                        )
            self.store.save()

        timeline = build_trust_timeline(self.store, alerts_path=self.alerts_path)

        report = DriftAlertReport(
            alerts=alerts,
            stable_count=stable,
            watch_count=watch,
            at_risk_count=at_risk,
            evaluated=len(alerts),
            timeline=timeline,
        )
        report.debug_trace = format_drift_trace(report)
        return report

    def _persist_snapshot(self, alerts: list[DriftAlert]) -> None:
        self.alerts_path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict[str, Any]] = []
        if self.alerts_path.exists():
            raw = json.loads(self.alerts_path.read_text(encoding="utf-8"))
            existing = list(raw.get("snapshots", []))

        now = datetime.now(timezone.utc).isoformat()
        existing.append(
            {
                "timestamp": now,
                "alerts": [a.to_dict() for a in alerts if a.alert_status != "stable"],
            }
        )
        payload = {
            "drift_version": DRIFT_VERSION,
            "snapshots": existing[-100:],
        }
        self.alerts_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def format_drift_trace(report: DriftAlertReport) -> str:
    lines = [
        "=== Shadow Drift Alerts | continuous trust degradation (v1) ===",
        f"  evaluated: {report.evaluated} | stable: {report.stable_count} | "
        f"watch: {report.watch_count} | at_risk: {report.at_risk_count}",
        "  early warning only — does not demote (see false_promotion_detector)",
    ]

    flagged = [a for a in report.alerts if a.alert_status != "stable"]
    if not flagged:
        lines.append("\n  No drift signals — promoted set stable.")
    else:
        lines.append("\n  Drift alerts:")
        for alert in sorted(flagged, key=lambda a: -a.severity):
            sig = alert.signals
            lines.append(
                f"\n  DRIFT ALERT [{alert.fp_id}] {alert.previous_status} -> {alert.alert_status.upper()}"
            )
            lines.append(
                f"    patch={alert.patch_id} class={alert.classification} severity={alert.severity:.2f}"
            )
            lines.append(
                f"    prod trend: {sig.prod_success_early:.2f} -> {sig.prod_success_late:.2f} "
                f"({sig.prod_trend_delta:+.2f} / {sig.window_observations} obs)"
            )
            lines.append(
                f"    sim-prod gap: {sig.shadow_gap_early:+.2f} -> {sig.shadow_gap_late:+.2f} "
                f"(widening {sig.gap_widening:+.2f})"
            )
            lines.append(
                f"    stability deriv={sig.stability_derivative:+.2f} "
                f"context entropy shift={sig.context_entropy_shift:.2f}"
            )
            lines.append(f"    flags: {', '.join(alert.flags) or '(none)'}")
            for action in alert.recommended_actions:
                lines.append(f"    -> {action.action}: {action.detail}")

    if report.timeline:
        lines.extend(["", "=== Trust Lifecycle Timeline (recent) ==="])
        for ev in report.timeline[-12:]:
            ts = ev.timestamp[:19] if ev.timestamp else "?"
            lines.append(
                f"  {ts} | {ev.fp_id[:12]:12s} | {ev.event_type:20s} | {ev.detail[:40]}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Shadow drift alerts — early trust degradation warning")
    parser.add_argument("--persist", action="store_true", help="Append snapshot to drift_alerts.json")
    parser.add_argument("--regression-check", action="store_true", help="CI: warn on monotonic at_risk drift trend")
    parser.add_argument("--strict", action="store_true", help="With --regression-check, fail on warning")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--learning", type=Path, default=None)
    parser.add_argument("--ingest", type=Path, default=None)
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW_SESSIONS)
    args = parser.parse_args(argv)

    if args.regression_check:
        from persona_ai.diagnostics.manifold_ci import ManifoldExit, check_shadow_drift_regression

        result = check_shadow_drift_regression()
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"  regression-check: {result.status} — {result.message}")
        if args.strict and result.exit_code == ManifoldExit.DRIFT_WARNING:
            return int(ManifoldExit.DRIFT_WARNING)
        return ManifoldExit.PASS if result.status in ("PASS", "SKIP", "WARN") else result.exit_code

    comparator = ShadowComparator(
        learning_path=args.learning,
        ingest_path=args.ingest,
    )
    monitor = ShadowDriftMonitor(
        PromotedLearningStore(args.store),
        comparator=comparator,
        window=args.window,
    )
    report = monitor.run(persist=args.persist)

    if args.json:
        payload = report.to_dict()
        payload["trace"] = report.debug_trace
        print(json.dumps(payload, indent=2))
    else:
        print(report.debug_trace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
