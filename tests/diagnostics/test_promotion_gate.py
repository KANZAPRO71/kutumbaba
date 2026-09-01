"""Promotion gate v1 tests."""

import json

from persona_ai.diagnostics.fingerprint_learning import FingerprintPatchLearner
from persona_ai.diagnostics.promotion_gate import (
    PromotedLearningStore,
    PromotionGate,
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


class TestPromotionRules:
    def test_promoted_when_all_gates_pass(self):
        decision = evaluate_comparison(_validated_row())
        assert decision.status == "PROMOTED"
        assert decision.rejection_code is None
        assert "validated_shadow_match" in decision.reasons

    def test_reject_overfit(self):
        row = _validated_row()
        row.classification = "simulation_overfit"
        decision = evaluate_comparison(row)
        assert decision.status == "REJECTED"
        assert decision.rejection_code == "OVERFIT"

    def test_reject_low_frequency(self):
        row = _validated_row()
        row.production.occurrences = 1
        decision = evaluate_comparison(row)
        assert decision.status == "REJECTED"
        assert decision.rejection_code == "NOISE"

    def test_reject_unstable(self):
        row = _validated_row()
        row.stability = 0.7
        decision = evaluate_comparison(row)
        assert decision.status == "REJECTED"
        assert decision.rejection_code == "UNSTABLE"

    def test_reject_drift(self):
        row = _validated_row()
        row.simulation.decayed_score = 0.95
        row.production.success_rate = 0.5
        decision = evaluate_comparison(row)
        assert decision.status == "REJECTED"
        assert decision.rejection_code == "DRIFT"


class TestPromotedStore:
    def test_persist_and_lookup(self, tmp_path):
        store_path = tmp_path / "promoted.json"
        store = PromotedLearningStore(store_path)
        gate = PromotionGate(store)
        decision = evaluate_comparison(_validated_row("fp_abc"))
        store.apply_decisions([decision])
        store.save()

        reloaded = PromotedLearningStore(store_path)
        assert reloaded.is_promoted("fp_abc", "raise_intent_need")

    def test_fast_path_requires_promotion(self, tmp_path, monkeypatch):
        promoted_path = tmp_path / "promoted.json"
        monkeypatch.setattr(
            "persona_ai.diagnostics.promotion_gate.get_promoted_store",
            lambda: PromotedLearningStore(promoted_path),
        )
        assert not is_trusted_for_fast_path("fp_x", "patch_a")

        store = PromotedLearningStore(promoted_path)
        store.apply_decisions([evaluate_comparison(_validated_row("fp_x"))])
        store.save()
        assert is_trusted_for_fast_path("fp_x", "raise_intent_need")


class TestIntegration:
    def test_full_pipeline_promote_overfit_case(self, tmp_path):
        learn_path = tmp_path / "learn.json"
        ingest_path = tmp_path / "ingest.json"
        promoted_path = tmp_path / "promoted.json"

        real_fp = "fp_x"
        ingest_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": [
                        {
                            "session_id": sid,
                            "timestamp": "2026-01-01T00:00:00+00:00",
                            "source": "smoke",
                            "context": "sarcasm_stack",
                            "fingerprints": [
                                {
                                    "fp_id": real_fp,
                                    "patch_suggestion": None,
                                    "decayed_score": None,
                                    "raw_score": None,
                                    "context": "sarcasm_stack",
                                    "outcome": "observed_failure",
                                    "turn_index": 0,
                                    "semantic_key": "FP::BDV_UNDER_RESPONSIVE::GENERIC::TEMPLATE_BYPASS",
                                }
                            ],
                            "system_snapshot": {"affects_runtime": False},
                            "contract_pass_rate": 1.0,
                            "readiness_score": 80.0,
                        }
                        for sid in ("p1", "p2", "p3", "p4", "p5")
                    ],
                }
            ),
            encoding="utf-8",
        )

        learner = FingerprintPatchLearner(learn_path)
        for _ in range(3):
            learner.record_simulation(real_fp, "raise_intent_need", fixes_failure=True)
        learner.save()

        gate = PromotionGate(PromotedLearningStore(promoted_path))
        report = gate.run(
            comparator=ShadowComparator(learning_path=learn_path, ingest_path=ingest_path),
            persist=True,
        )
        assert report.promoted_count == 0
        assert any(d.rejection_code == "OVERFIT" for d in report.decisions)
        assert PromotedLearningStore(promoted_path).active_count == 0
