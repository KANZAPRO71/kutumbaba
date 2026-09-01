"""Persona pilot integration and A/B harness tests."""

from __future__ import annotations

import json

from persona_ai.core.types import SpeakAction
from persona_ai.eval.ab_experiment import run_experiment, run_scenario
from persona_ai.eval.human_eval import (
    HumanEvalScores,
    generate_blind_pairs,
    record_human_eval,
    reviewer_form,
    summarize_human_evals,
)
from persona_ai.eval.scenarios import SCENARIO_BY_ID, SCENARIOS
from persona_ai.integrations.gemini_direct import GeminiDirectClient
from persona_ai.integrations.persona_eval import PersonaEvalClient
from tests.support.stub_llm import StubLLMAdapter


class TestPersonaEvalClient:
    def test_process_turn_delegates_to_runtime(self):
        client = PersonaEvalClient(llm_adapter=StubLLMAdapter())
        out = client.process_turn("eval-1", "Besok meeting jam berapa?")
        assert out.text
        assert client.preset_id == "default_companion"

    def test_does_not_expose_internal_modules(self):
        client = PersonaEvalClient()
        assert hasattr(client, "process_turn")
        assert hasattr(client, "runtime")


class TestGeminiDirectControl:
    def test_always_calls_llm_renderer(self):
        client = GeminiDirectClient(llm_adapter=StubLLMAdapter())
        text = client.process_turn("c1", "Oke")
        assert text


class TestPilotABHarness:
    def test_run_single_closure_scenario(self):
        scenario = SCENARIO_BY_ID["closure_after_long"]
        control = GeminiDirectClient(llm_adapter=StubLLMAdapter())
        treatment = PersonaEvalClient(llm_adapter=StubLLMAdapter())
        result = run_scenario(scenario, control=control, treatment=treatment)
        assert result.scenario_id == "closure_after_long"
        assert result.control_model == "gemini-direct"
        assert result.treatment_model == "stub"
        assert result.persona_preset == "default_companion"
        assert result.bdv == SpeakAction.SILENCE.value
        assert result.treatment_text is None

    def test_run_experiment_produces_all_scenarios(self):
        results = run_experiment()
        assert len(results) == len(SCENARIOS)
        assert {row["scenario_id"] for row in results} == {s.scenario_id for s in SCENARIOS}

    def test_same_adapter_model_identity(self):
        adapter = StubLLMAdapter()
        results = run_experiment(control_adapter=adapter, treatment_adapter=adapter)
        for row in results:
            assert row["control_model"] == row["treatment_model"] == "stub"

    def test_unfinished_thought_defer(self):
        scenario = SCENARIO_BY_ID["unfinished_thought"]
        control = GeminiDirectClient(llm_adapter=StubLLMAdapter())
        treatment = PersonaEvalClient(llm_adapter=StubLLMAdapter())
        result = run_scenario(scenario, control=control, treatment=treatment)
        assert result.bdv == SpeakAction.DEFER.value


class TestHumanEvalBlindPairs:
    def test_generate_blind_pairs_randomizes_order(self):
        results = [
            {
                "scenario_id": "s1",
                "control_text": "plain reply A",
                "treatment_text": "plain reply B",
            }
        ]
        pairs = generate_blind_pairs(results)
        assert len(pairs) == 1
        form = reviewer_form(pairs[0])
        assert "transcript_a" in form
        assert "treatment" not in json.dumps(form).lower()
        assert "persona" not in json.dumps(form).lower()

    def test_record_and_summarize(self, tmp_path):
        path = tmp_path / "scores.jsonl"
        record_human_eval(
            HumanEvalScores(
                pair_id="p1",
                scenario_id="s1",
                naturalness=6,
                timing=5,
                intrusiveness=4,
                emotional_fit=6,
                preference="A",
            ),
            store_path=path,
        )
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        summary = summarize_human_evals(rows)
        assert summary["count"] == 1
        assert summary["metrics"]["naturalness"]["mean"] == 6.0
