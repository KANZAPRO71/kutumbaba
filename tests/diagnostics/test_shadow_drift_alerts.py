"""Shadow drift alerts v1 tests."""

import json
from datetime import datetime, timezone

from persona_ai.diagnostics.promotion_gate import PromotedLearning, PromotedLearningStore
from persona_ai.diagnostics.shadow_comparator import (
    DomainMetrics,
    FingerprintShadowComparison,
    ShadowDelta,
)
from persona_ai.diagnostics.shadow_drift_alerts import (
    PROD_TREND_ALERT,
    ShadowDriftMonitor,
    compute_drift_signals,
    evaluate_drift,
)


def _promoted(fp_id: str = "fp_drift") -> PromotedLearning:
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


def _shadow_row(fp_id: str = "fp_drift") -> FingerprintShadowComparison:
    return FingerprintShadowComparison(
        fp_id=fp_id,
        semantic_key="FP::DRIFT",
        simulation=DomainMetrics(success_rate=0.88, decayed_score=0.88, attempts=5, primary_patch="raise_intent_need"),
        production=DomainMetrics(success_rate=0.70, occurrences=6),
        delta=ShadowDelta(success_gap=0.18, confidence_gap=0.1),
        classification="watch",
        stability=0.72,
    )


def _prod_entries(fp_id: str, *, early_success: bool, late_success: bool) -> list[dict]:
    entries = []
    for i, ok in enumerate([True, True, True, early_success, early_success, late_success, late_success, late_success]):
        outcome = "observed_success" if ok else "observed_failure"
        ctx = "semantic_chaos" if i < 4 else "sarcasm_stack"
        entries.append(
            {
                "session_id": f"s{i}",
                "timestamp": f"2026-01-{i+1:02d}T00:00:00",
                "context": ctx,
                "fingerprints": [{"fp_id": fp_id, "outcome": outcome}],
            }
        )
    return entries


class TestDriftSignals:
    def test_stable_when_insufficient_data(self):
        row = _shadow_row()
        row.stability = 0.92
        signals = compute_drift_signals(_promoted(), shadow_row=row, prod_entries=[])
        assert signals.window_observations == 0
        assert "prod_success_declining" not in signals.active_flags()

    def test_prod_decline_detected(self):
        fp = "fp_decline"
        entries = _prod_entries(fp, early_success=True, late_success=False)
        signals = compute_drift_signals(
            _promoted(fp),
            shadow_row=_shadow_row(fp),
            prod_entries=entries,
        )
        assert signals.prod_trend_delta <= PROD_TREND_ALERT
        assert "prod_success_declining" in signals.active_flags()

    def test_gap_widening_detected(self):
        fp = "fp_gap"
        entries = _prod_entries(fp, early_success=True, late_success=False)
        row = _shadow_row(fp)
        row.simulation.decayed_score = 0.95
        signals = compute_drift_signals(_promoted(fp), shadow_row=row, prod_entries=entries)
        flags = signals.active_flags()
        assert "sim_prod_gap_widening" in flags or "prod_success_declining" in flags
class TestDriftAlert:
    def test_at_risk_on_compound_signals(self):
        fp = "fp_risk"
        entries = _prod_entries(fp, early_success=True, late_success=False)
        alert = evaluate_drift(_promoted(fp), shadow_row=_shadow_row(fp), prod_entries=entries)
        assert alert.alert_status in ("watch", "at_risk")
        assert alert.classification != "STABLE"
        assert alert.elasticity_weight < 1.0
        assert any(a.action == "reduce_fast_path_weight" for a in alert.recommended_actions)

    def test_stable_when_healthy(self):
        fp = "fp_ok"
        entries = []
        for i in range(8):
            entries.append(
                {
                    "session_id": f"s{i}",
                    "timestamp": f"2026-01-{i+1:02d}T00:00:00",
                    "context": "semantic_chaos",
                    "fingerprints": [{"fp_id": fp, "outcome": "observed_success"}],
                }
            )
        row = _shadow_row(fp)
        row.production.success_rate = 0.85
        row.stability = 0.91
        promoted = _promoted(fp)
        promoted.baseline_stability = 0.91
        alert = evaluate_drift(promoted, shadow_row=row, prod_entries=entries)
        assert alert.alert_status == "stable"
        assert alert.classification == "STABLE"


class TestDriftMonitor:
    def test_persist_and_timeline(self, tmp_path):
        store_path = tmp_path / "promoted.json"
        alerts_path = tmp_path / "drift.json"
        ingest_path = tmp_path / "ingest.json"
        learn_path = tmp_path / "learn.json"

        entry = _promoted("fp_mon")
        store = PromotedLearningStore(store_path)
        store.entries[store._key("fp_mon", "raise_intent_need")] = entry
        store.save()

        ingest_path.write_text(
            json.dumps({"entries": _prod_entries("fp_mon", early_success=True, late_success=False)})
        )
        learn_path.write_text(json.dumps({"version": "v1.2", "entries": {}}))

        row = _shadow_row("fp_mon")

        class StubComparator:
            def __init__(self, path):
                self.ingest_path = path

            def build_report(self):
                from persona_ai.diagnostics.shadow_comparator import ShadowReport

                return ShadowReport(
                    comparisons=[row],
                    patch_summaries=[],
                    timeline=[],
                    avg_generalization_gap=0.2,
                    validated_pct=0.0,
                    overfit_pct=0.0,
                    undermodeled_pct=0.0,
                    noise_pct=0.0,
                )

        monitor = ShadowDriftMonitor(
            PromotedLearningStore(store_path),
            comparator=StubComparator(ingest_path),
            alerts_path=alerts_path,
        )
        report = monitor.run(persist=True)

        assert report.evaluated == 1
        assert alerts_path.exists()
        assert any(e.event_type == "promoted" for e in report.timeline)
