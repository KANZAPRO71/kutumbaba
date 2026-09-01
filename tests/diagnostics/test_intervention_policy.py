"""Intervention policy layer tests."""

from persona_ai.core.types import SpeakAction
from persona_ai.diagnostics.failure_taxonomy import FailureClass, FailureDomain, FailureEvent, FailureSeverity
from persona_ai.diagnostics.intervention_policy import InterventionPolicy, PATCH_PRIORS
from persona_ai.diagnostics.counterfactual import Intervention
from persona_ai.diagnostics.turn_context import TurnCausalContext
from tests.support.stub_llm import StubLLMAdapter
from persona_ai.sim.smoke_openai import run_smoke


class TestPolicyScoring:
    def test_defer_prior_prefers_incompleteness(self):
        policy = InterventionPolicy()
        failure = FailureEvent(
            5, FailureDomain.BDV, FailureClass.BDV_DEFER_MISS,
            FailureSeverity.STRUCTURAL, "defer",
        )
        ctx = TurnCausalContext(incompleteness_score=0.0)
        iv_inc = Intervention("raise_incompleteness", "interpret", "incompleteness_score")
        iv_boost = Intervention("boost_defer_pressure", "pressure", "defer_pressure")
        s_inc = policy.score(iv_inc, failure, ctx, "interpret.incompleteness_score")
        s_boost = policy.score(iv_boost, failure, ctx, "pressure.defer_pressure")
        assert s_inc > s_boost

    def test_prune_reduces_search_space(self):
        policy = InterventionPolicy(max_interventions=2)
        failure = FailureEvent(
            0, FailureDomain.BDV, FailureClass.BDV_UNDER_RESPONSIVE,
            FailureSeverity.DEGRADED, "under",
        )
        interventions = [
            Intervention("raise_intent_need", "interpret", "intent_need"),
            Intervention("classify_direct_question", "interpret", "q"),
            Intervention("mixed_intent_priority", "interpret", "mixed"),
            Intervention("causal_intent_floor", "interpret", "floor"),
        ]
        pruned, pr = policy.prune(interventions, failure, TurnCausalContext(), "interpret.intent_need")
        assert pr.pruned_count <= 2
        assert pr.search_reduction_pct > 0
        assert pr.skipped_pairs >= 0


class TestCompatibility:
    def test_incompatible_intent_need_bundles(self):
        policy = InterventionPolicy()
        assert not policy.compatible_bundle(["raise_intent_need", "classify_direct_question"])
        assert policy.compatible_bundle(["raise_intent_need"])

    def test_incompatible_defer_bundles(self):
        policy = InterventionPolicy()
        assert not policy.compatible_bundle(["boost_defer_pressure", "raise_incompleteness"])


class TestSmokeIntegration:
    def test_smoke_includes_policy_layer(self):
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        assert report.failure.intervention_policy is not None
        assert "Intervention Policy" in report.failure.debug_trace
        assert report.failure.intervention_policy.total_simulations_avoided >= 0

    def test_policy_predictions_match_failure_type(self):
        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        pr = report.failure.intervention_policy
        assert pr.prune_stats == []

    def test_priors_registry_covers_key_failures(self):
        classes = {fc for p in PATCH_PRIORS for fc in p.failure_classes}
        assert FailureClass.BDV_DEFER_MISS in classes
        assert FailureClass.BDV_UNDER_RESPONSIVE in classes
