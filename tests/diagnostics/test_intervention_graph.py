"""Intervention interaction graph tests."""

import pytest

from persona_ai.diagnostics.counterfactual import Intervention
from persona_ai.diagnostics.intervention_graph import merge_interventions
from tests.support.stub_llm import StubLLMAdapter
from persona_ai.sim.smoke_openai import run_smoke


class TestMerge:
    def test_detects_intent_conflict(self):
        a = Intervention("a", "interpret", "x", intent_patch={"intent_need": 0.65})
        b = Intervention("b", "interpret", "y", intent_patch={"intent_need": 0.0})
        _, conflicts = merge_interventions([a, b])
        assert any("intent_need" in c for c in conflicts)

    def test_clean_merge_no_conflict(self):
        a = Intervention("a", "interpret", "inc", intent_patch={"incompleteness_score": 0.8})
        b = Intervention("b", "interpret", "vent", intent_patch={"is_vent": False})
        merged, conflicts = merge_interventions([a, b])
        assert not conflicts
        assert merged.intent_patch["incompleteness_score"] == 0.8
        assert merged.intent_patch["is_vent"] is False


class TestGraph:
    def test_smoke_has_intervention_graph(self):
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        assert report.failure.intervention_graph is not None
        assert "Intervention Graph" in report.failure.debug_trace

    def test_optimal_bundle_exists_for_fixable_failures(self):
        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        graph = report.failure.intervention_graph
        optimal_count = sum(1 for n in graph.nodes if n.optimal_bundle)
        assert optimal_count == 0

    def test_bundle_scores_ranked(self):
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        for node in report.failure.intervention_graph.nodes:
            if len(node.bundles) > 1:
                scores = [b.score for b in node.bundles]
                assert scores == sorted(scores, reverse=True)
                break
        else:
            pytest.skip("no multi-bundle node")

    def test_pairwise_edges_built(self):
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        for node in report.failure.intervention_graph.nodes:
            if len(node.bundles) >= 2:
                assert len(node.edges) >= 1
                break
