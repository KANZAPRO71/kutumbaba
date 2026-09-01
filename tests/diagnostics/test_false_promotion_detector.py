"""False promotion detection v1 tests."""

import json
from datetime import datetime, timezone

from persona_ai.diagnostics.false_promotion_detector import (
    FalsePromotionDetector,
    evaluate_promoted_entry,
)
from persona_ai.diagnostics.promotion_gate import (
    PromotedLearning,
    PromotedLearningStore,
    evaluate_comparison,
    is_trusted_for_fast_path,
)
from persona_ai.diagnostics.shadow_comparator import (
    DomainMetrics,
    FingerprintShadowComparison,
    ShadowComparator,
    ShadowDelta,
)


def _validated_row(fp_id: str = "fp_test") -> FingerprintShadowComparison:
    return FingerprintShadowComparison(
        fp_id=fp_id,
        semantic_key="FP::TEST",
        simulation=DomainMetrics(
            success_rate=0.9,
            attempts=5,
            decayed_score=0.88,
            primary_patch="raise_intent_need",
        ),
        production=DomainMetrics(success_rate=0.85, occurrences=5),
        delta=ShadowDelta(success_gap=0.05, confidence_gap=0.1, score_gap=0.03),
        classification="validated",
        stability=0.92,
    )


def _promoted_entry(fp_id: str = "fp_test") -> PromotedLearning:
    now = datetime.now(timezone.utc).isoformat()
    return PromotedLearning(
        fp_id=fp_id,
        patch_id="raise_intent_need",
        first_promoted=now,
        last_evaluated=now,
        last_status_change=now,
        stability=0.92,
        confidence=0.88,
        baseline_stability=0.92,
        baseline_prod_score=0.85,
        baseline_sim_score=0.88,
    )


class TestDetectionSignals:
    def test_no_flags_when_healthy(self):
        finding = evaluate_promoted_entry(
            _promoted_entry(),
            shadow_row=_validated_row(),
            prod_entries=[],
        )
        assert finding is None

    def test_post_promotion_failure(self):
        row = _validated_row()
        row.production.success_rate = 0.3
        row.production.occurrences = 4
        row.stability = 0.55
        row.classification = "simulation_overfit"

        finding = evaluate_promoted_entry(_promoted_entry(), shadow_row=row, prod_entries=[])
        assert finding is not None
        assert "post_promotion_failure" in finding.flags
        assert finding.false_promotion_class in ("PREMATURE_PROMOTION", "SIMULATION_BIAS")
        assert finding.severity >= 0.5

    def test_stability_collapse(self):
        row = _validated_row()
        row.stability = 0.5
        row.production.success_rate = 0.7
        row.production.occurrences = 5

        finding = evaluate_promoted_entry(_promoted_entry(), shadow_row=row, prod_entries=[])
        assert finding is not None
        assert "unstable_generalization" in finding.flags

    def test_shadow_overconfidence(self):
        row = _validated_row()
        row.classification = "simulation_overfit"
        row.production.success_rate = 0.6
        row.production.occurrences = 5
        row.stability = 0.65

        finding = evaluate_promoted_entry(_promoted_entry(), shadow_row=row, prod_entries=[])
        assert finding is not None
        assert "shadow_overconfidence" in finding.flags
        assert finding.false_promotion_class == "SIMULATION_BIAS"

    def test_context_shift(self):
        row = _validated_row()
        entries = []
        for i in range(6):
            ctx = "semantic_chaos" if i < 3 else "sarcasm_stack"
            entries.append(
                {
                    "timestamp": f"2026-01-0{i}T00:00:00",
                    "context": ctx,
                    "fingerprints": [{"fp_id": "fp_test", "outcome": "observed_failure"}],
                }
            )

        finding = evaluate_promoted_entry(_promoted_entry(), shadow_row=row, prod_entries=entries)
        assert finding is not None
        assert "context_shift_mismatch" in finding.flags
        assert finding.false_promotion_class == "CONTEXT_SHIFT"


class TestLifecycle:
    def test_quarantine_removes_fast_path(self, tmp_path, monkeypatch):
        store_path = tmp_path / "promoted.json"
        store = PromotedLearningStore(store_path)
        store.apply_decisions([evaluate_comparison(_validated_row("fp_q"))])
        store.save()

        monkeypatch.setattr(
            "persona_ai.diagnostics.promotion_gate.get_promoted_store",
            lambda: PromotedLearningStore(store_path),
        )
        assert is_trusted_for_fast_path("fp_q", "raise_intent_need")

        store.apply_lifecycle_update(
            "fp_q",
            "raise_intent_need",
            status="quarantined",
            false_promotion_class="SIMULATION_BIAS",
            monitoring_flags=["shadow_overconfidence"],
        )
        store.save()

        reloaded = PromotedLearningStore(store_path)
        assert not reloaded.is_promoted("fp_q", "raise_intent_need")
        assert not is_trusted_for_fast_path("fp_q", "raise_intent_need")

    def test_demoted_skipped_on_re_evaluate(self, tmp_path):
        store_path = tmp_path / "promoted.json"
        store = PromotedLearningStore(store_path)
        entry = _promoted_entry("fp_d")
        store.entries[store._key("fp_d", "raise_intent_need")] = entry
        store.apply_lifecycle_update("fp_d", "raise_intent_need", status="demoted")
        store.save()

        learn_path = tmp_path / "learn.json"
        ingest_path = tmp_path / "ingest.json"
        ingest_path.write_text(json.dumps({"entries": []}))

        detector = FalsePromotionDetector(
            PromotedLearningStore(store_path),
            comparator=ShadowComparator(learning_path=learn_path, ingest_path=ingest_path),
        )
        report = detector.run(persist=False)
        assert report.evaluated == 1
        assert report.flagged == 0


class TestDetectorIntegration:
    def test_persist_lifecycle_updates_store(self, tmp_path):
        store_path = tmp_path / "promoted.json"
        ingest_path = tmp_path / "ingest.json"
        learn_path = tmp_path / "learn.json"

        store = PromotedLearningStore(store_path)
        store.apply_decisions([evaluate_comparison(_validated_row("fp_bad"))])
        store.save()

        ingest_path.write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "session_id": "s1",
                            "timestamp": "2026-01-01T00:00:00",
                            "context": "sarcasm_stack",
                            "fingerprints": [
                                {"fp_id": "fp_bad", "outcome": "observed_failure", "semantic_key": "X"}
                            ],
                        }
                        for _ in range(5)
                    ]
                }
            )
        )
        learn_path.write_text(json.dumps({"version": "v1.2", "entries": {}}))

        row = _validated_row("fp_bad")
        row.production.success_rate = 0.2
        row.production.occurrences = 5
        row.classification = "simulation_overfit"
        row.stability = 0.4

        class StubComparator(ShadowComparator):
            def build_report(self):
                from persona_ai.diagnostics.shadow_comparator import ShadowReport

                return ShadowReport(
                    comparisons=[row],
                    patch_summaries=[],
                    timeline=[],
                    avg_generalization_gap=0.7,
                    validated_pct=0.0,
                    overfit_pct=1.0,
                    undermodeled_pct=0.0,
                    noise_pct=0.0,
                )

        detector = FalsePromotionDetector(
            PromotedLearningStore(store_path),
            comparator=StubComparator(learning_path=learn_path, ingest_path=ingest_path),
            audit_path=tmp_path / "audit.json",
        )
        report = detector.run(persist=True)

        assert report.flagged >= 1
        reloaded = PromotedLearningStore(store_path)
        entry = reloaded.get("fp_bad", "raise_intent_need")
        assert entry is not None
        assert entry.status in ("degraded", "quarantined", "demoted")
        assert entry.false_promotion_class is not None
        assert (tmp_path / "audit.json").exists()
