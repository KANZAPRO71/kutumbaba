"""Trust decision engine v1 tests."""

import json
from datetime import datetime, timezone

from persona_ai.diagnostics.promotion_gate import PromotedLearning, PromotedLearningStore
from persona_ai.diagnostics.shadow_comparator import (
    DomainMetrics,
    FingerprintShadowComparison,
    ShadowDelta,
)
from persona_ai.diagnostics.shadow_drift_alerts import DriftAlert, DriftSignals, evaluate_drift
from persona_ai.diagnostics.trust_decision_engine import (
    ESCALATION_MIN_SEVERITY,
    ESCALATION_MIN_STREAK,
    TrustDecisionEngine,
    compute_at_risk_streak,
    evaluate_trust_decision,
)


def _promoted(fp_id: str = "fp_dec") -> PromotedLearning:
    now = datetime.now(timezone.utc).isoformat()
    return PromotedLearning(
        fp_id=fp_id,
        patch_id="raise_intent_need",
        first_promoted=now,
        last_evaluated=now,
        last_status_change=now,
        stability=0.90,
        confidence=0.88,
        baseline_stability=0.92,
        baseline_prod_score=0.85,
        baseline_sim_score=0.88,
    )


def _at_risk_alert(fp_id: str = "fp_dec", severity: float = 0.72) -> DriftAlert:
    signals = DriftSignals(
        prod_success_early=0.92,
        prod_success_late=0.64,
        prod_trend_delta=-0.28,
        shadow_gap_early=0.10,
        shadow_gap_late=0.24,
        gap_widening=0.14,
        stability_current=0.70,
        stability_derivative=-0.22,
        window_observations=8,
    )
    return DriftAlert(
        fp_id=fp_id,
        patch_id="raise_intent_need",
        previous_status="active",
        alert_status="at_risk",
        classification="EARLY_DEGRADATION",
        severity=severity,
        elasticity_weight=0.42,
        signals=signals,
        flags=["prod_success_declining", "stability_erosion"],
        recommended_actions=[],
    )


class TestDecisionRules:
    def test_escalation_rule(self):
        alert = _at_risk_alert(severity=0.72)
        decision = evaluate_trust_decision(
            alert,
            at_risk_streak=ESCALATION_MIN_STREAK,
            prior_at_risk_streak=1,
            false_promotion_flagged=False,
            prod_variance=0.2,
        )
        assert decision.recommendation == "QUARANTINE_REVIEW"
        assert decision.decision_state == "ESCALATION_CANDIDATE"
        assert "ESCALATION_CANDIDATE" in decision.drift_state
        assert decision.confidence >= 0.5

    def test_escalation_blocked_by_volatility_shield(self):
        alert = _at_risk_alert(severity=0.65)
        decision = evaluate_trust_decision(
            alert,
            at_risk_streak=ESCALATION_MIN_STREAK,
            prior_at_risk_streak=2,
            false_promotion_flagged=False,
            prod_variance=0.45,
        )
        assert decision.recommendation == "MONITOR_EXTEND"
        assert decision.decision_state == "VOLATILITY_HOLD"

    def test_structural_demotion_recommendation(self):
        alert = _at_risk_alert()
        alert.signals.prod_trend_delta = -0.30
        alert.signals.gap_widening = 0.25
        decision = evaluate_trust_decision(
            alert,
            at_risk_streak=1,
            prior_at_risk_streak=0,
            false_promotion_flagged=True,
            prod_variance=0.2,
        )
        assert decision.recommendation == "DEMOTION_RECOMMENDATION"
        assert decision.decision_state == "DEMOTION_CANDIDATE"

    def test_recovery_rule(self):
        alert = _at_risk_alert()
        alert.alert_status = "watch"
        alert.signals.stability_derivative = 0.08
        decision = evaluate_trust_decision(
            alert,
            at_risk_streak=1,
            prior_at_risk_streak=3,
            false_promotion_flagged=False,
            prod_variance=0.15,
        )
        assert decision.recommendation == "RECOVERY_STABLE"
        assert decision.decision_state == "RECOVERING"

    def test_maintain_when_stable(self):
        alert = _at_risk_alert()
        alert.alert_status = "stable"
        alert.severity = 0.0
        alert.signals.prod_trend_delta = 0.0
        decision = evaluate_trust_decision(
            alert,
            at_risk_streak=0,
            prior_at_risk_streak=0,
            false_promotion_flagged=False,
            prod_variance=0.1,
        )
        assert decision.recommendation == "MAINTAIN"


class TestStreakComputation:
    def test_consecutive_at_risk_streak(self):
        snapshots = [
            {"alerts": [{"fp_id": "fp_x", "patch_id": "p1", "alert_status": "at_risk"}]},
            {"alerts": [{"fp_id": "fp_x", "patch_id": "p1", "alert_status": "at_risk"}]},
            {"alerts": [{"fp_id": "fp_x", "patch_id": "p1", "alert_status": "watch"}]},
            {"alerts": [{"fp_id": "fp_x", "patch_id": "p1", "alert_status": "at_risk"}]},
        ]
        streak, prior = compute_at_risk_streak(snapshots, "fp_x", "p1")
        assert streak == 1
        assert prior == 2


class TestEngineIntegration:
    def test_apply_quarantine(self, tmp_path, monkeypatch):
        store_path = tmp_path / "promoted.json"
        alerts_path = tmp_path / "drift.json"
        ingest_path = tmp_path / "ingest.json"
        learn_path = tmp_path / "learn.json"

        store = PromotedLearningStore(store_path)
        store.entries[store._key("fp_q", "raise_intent_need")] = _promoted("fp_q")
        store.save()

        snapshots = []
        for _ in range(ESCALATION_MIN_STREAK):
            snapshots.append(
                {
                    "timestamp": "2026-01-01T00:00:00",
                    "alerts": [
                        {
                            "fp_id": "fp_q",
                            "patch_id": "raise_intent_need",
                            "alert_status": "at_risk",
                            "severity": ESCALATION_MIN_SEVERITY + 0.1,
                        }
                    ],
                }
            )
        alerts_path.write_text(json.dumps({"snapshots": snapshots}))
        fp_id = "fp_q"
        ingest_path.write_text(json.dumps({"entries": []}))
        learn_path.write_text(json.dumps({"version": "v1.2", "entries": {}}))

        row = FingerprintShadowComparison(
            fp_id=fp_id,
            semantic_key="X",
            simulation=DomainMetrics(success_rate=0.82, decayed_score=0.82, attempts=5, primary_patch="raise_intent_need"),
            production=DomainMetrics(success_rate=0.62, occurrences=8),
            delta=ShadowDelta(success_gap=0.20, confidence_gap=0.1),
            classification="watch",
            stability=0.72,
        )

        class StubComparator:
            def __init__(self, path):
                self.ingest_path = path

            def build_report(self):
                from persona_ai.diagnostics.shadow_comparator import ShadowReport

                return ShadowReport(
                    comparisons=[row],
                    patch_summaries=[],
                    timeline=[],
                    avg_generalization_gap=0.4,
                    validated_pct=0.0,
                    overfit_pct=1.0,
                    undermodeled_pct=0.0,
                    noise_pct=0.0,
                )

        engine = TrustDecisionEngine(
            PromotedLearningStore(store_path),
            comparator=StubComparator(ingest_path),
            alerts_path=alerts_path,
        )

        class EmptyFPReport:
            findings = []

        monkeypatch.setattr(
            "persona_ai.diagnostics.trust_decision_engine.FalsePromotionDetector.run",
            lambda self, persist=False: EmptyFPReport(),
        )
        monkeypatch.setattr(
            "persona_ai.diagnostics.trust_decision_engine.ShadowDriftMonitor.run",
            lambda self, persist=False: type("R", (), {
                "alerts": [_at_risk_alert("fp_q", severity=0.72)],
            })(),
        )
        report = engine.run(persist=False, apply_quarantine=True)

        assert report.quarantine_candidates >= 1
        reloaded = PromotedLearningStore(store_path)
        entry = reloaded.get("fp_q", "raise_intent_need")
        assert entry is not None
        assert entry.status == "quarantined"
