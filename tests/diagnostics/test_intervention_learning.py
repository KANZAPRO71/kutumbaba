"""Intervention prior learning + fingerprint learning tests."""

from pathlib import Path

import pytest

from persona_ai.diagnostics.counterfactual import Intervention
from persona_ai.diagnostics.failure_fingerprint import build_fingerprint
from persona_ai.diagnostics.failure_taxonomy import (
    FailureClass,
    FailureDomain,
    FailureEvent,
    FailureReport,
    FailureSeverity,
)
from persona_ai.diagnostics.fingerprint_learning import FingerprintPatchLearner
from persona_ai.diagnostics.intervention_learning import (
    PriorLearner,
    build_learning_report,
    ingest_from_diagnostic_run,
)
from persona_ai.diagnostics.turn_context import TurnCausalContext
from tests.support.stub_llm import StubLLMAdapter
from persona_ai.sim.drift_harness import TurnRecord
from persona_ai.sim.smoke_openai import run_smoke


@pytest.fixture
def learner(tmp_path: Path) -> PriorLearner:
    return PriorLearner(tmp_path / "priors.json")


@pytest.fixture
def fp_learner(tmp_path: Path) -> FingerprintPatchLearner:
    return FingerprintPatchLearner(tmp_path / "fp_learning.json")


class TestPriorLearner:
    def test_seed_from_static(self, learner: PriorLearner):
        assert learner.store_size >= 8
        rate, conf = learner.predict_rate(
            FailureClass.BDV_DEFER_MISS, "raise_incompleteness", TurnCausalContext()
        )
        assert rate > 0.5
        assert conf > 0

    def test_observe_increases_confidence(self, learner: PriorLearner):
        ctx = TurnCausalContext(incompleteness_score=0.0)
        for _ in range(4):
            learner.observe(FailureClass.BDV_DEFER_MISS, "raise_incompleteness", True, ctx)
        _, conf = learner.predict_rate(FailureClass.BDV_DEFER_MISS, "raise_incompleteness", ctx)
        assert conf >= 0.6

    def test_predict_best_ranks_patches(self, learner: PriorLearner):
        failure = FailureEvent(
            0, FailureDomain.BDV, FailureClass.BDV_DEFER_MISS,
            FailureSeverity.STRUCTURAL, "defer",
        )
        ivs = [
            Intervention("raise_incompleteness", "interpret", "inc"),
            Intervention("boost_defer_pressure", "pressure", "def"),
        ]
        preds = learner.predict_best(failure, ivs, TurnCausalContext(incompleteness_score=0.0), "interpret.incompleteness_score")
        assert preds[0].blended_score >= preds[-1].blended_score

    def test_persistence_round_trip(self, tmp_path: Path):
        path = tmp_path / "priors.json"
        l1 = PriorLearner(path)
        l1.observe(FailureClass.BDV_DEFER_MISS, "raise_incompleteness", True, TurnCausalContext())
        l1.save()
        l2 = PriorLearner(path)
        assert l2.store_size >= l1.store_size


class TestFingerprintPatchLearner:
    def test_score_penalizes_regressions(self, fp_learner: FingerprintPatchLearner):
        fp_learner.record_simulation("fp_abc", "raise_incompleteness", fixes_failure=True)
        fp_learner.record_simulation("fp_abc", "raise_incompleteness", fixes_failure=True)
        fp_learner.record_regression("fp_abc", "raise_incompleteness")
        preds = fp_learner.predict_best("fp_abc", ["raise_incompleteness"])
        assert preds[0].decayed_score < preds[0].raw_score

    def test_fast_path_requires_attempts_and_score(self, fp_learner: FingerprintPatchLearner):
        fp_learner.record_simulation("fp_x", "patch_a", fixes_failure=True)
        preds = fp_learner.predict_best("fp_x", ["patch_a"])
        assert not fp_learner.fast_path_eligible(preds[0])
        fp_learner.record_simulation("fp_x", "patch_a", fixes_failure=True)
        preds = fp_learner.predict_best("fp_x", ["patch_a"])
        assert fp_learner.fast_path_eligible(preds[0])

    def test_persistence_round_trip(self, tmp_path: Path):
        path = tmp_path / "fp.json"
        l1 = FingerprintPatchLearner(path)
        l1.record_simulation("fp_a", "patch_b", fixes_failure=True)
        l1.save()
        l2 = FingerprintPatchLearner(path)
        assert l2.store_size == 1


class TestIntegration:
    def test_smoke_includes_learning_layer(self):
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        assert report.failure.intervention_learning is not None
        trace = report.failure.debug_trace
        assert "Intervention Learning" in trace
        assert "equilibrium arbitration" in trace or "cross-cluster" in trace

    def test_learning_has_predictions(self):
        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        lr = report.failure.intervention_learning
        assert not lr.predictions
        assert not lr.fingerprint_recommendations

    def test_ingest_records_fp_outcomes(self, learner: PriorLearner, fp_learner: FingerprintPatchLearner):
        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        count = ingest_from_diagnostic_run(learner, report.failure, report.session, fp_learner)
        assert count == 0
        assert fp_learner.store_size == 0

    def test_build_report_prefers_fingerprint_key(self, learner: PriorLearner, fp_learner: FingerprintPatchLearner):
        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        fp_id = "fp_synthetic"
        for _ in range(3):
            fp_learner.record_simulation(fp_id, "raise_intent_need", fixes_failure=True)
        ingest_from_diagnostic_run(learner, report.failure, report.session, fp_learner)
        lr = build_learning_report(learner, report.failure, report.session, fp_learner)
        assert all(p.fingerprint_id != fp_id for p in lr.predictions)
