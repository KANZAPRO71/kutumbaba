"""Smoke test harness — deterministic stub in CI; live OpenAI/Gemini when keys set."""

import os

import pytest

from persona_ai.llm.adapter import OpenAILLMAdapter
from persona_ai.sim.adversarial_scripts import ADVERSARIAL_SCRIPTS
from persona_ai.sim.smoke_openai import compare_gemini_vs_openai, run_smoke
from tests.support.stub_llm import StubLLMAdapter

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
needs_openai = pytest.mark.skipif(not OPENAI_KEY, reason="OPENAI_API_KEY not set")
needs_gemini_and_openai = pytest.mark.skipif(
    not OPENAI_KEY or not GEMINI_KEY,
    reason="GEMINI_API_KEY and OPENAI_API_KEY required",
)


class TestSmokeDeterministic:
    @pytest.mark.parametrize("script_name", list(ADVERSARIAL_SCRIPTS.keys()))
    def test_deterministic_smoke_grade(self, script_name: str):
        report = run_smoke(script_name, StubLLMAdapter())
        assert report.smoke.grade in ("A", "B"), (
            f"{script_name}: grade={report.smoke.grade} notes={report.smoke.notes}"
        )

    @pytest.mark.parametrize("script_name", list(ADVERSARIAL_SCRIPTS.keys()))
    def test_behavior_contracts(self, script_name: str):
        report = run_smoke(script_name, StubLLMAdapter())
        assert report.smoke.contract_pass_rate >= 0.6, report.smoke.behavior_contracts

    def test_semantic_chaos_silence_turn(self):
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        closure = next(c for c in report.smoke.behavior_contracts if c.tag == "closure_after_long")
        assert closure.passed, closure.violation

    def test_sarcasm_vent_ack(self):
        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        vent = next(c for c in report.smoke.behavior_contracts if c.tag == "vent_rhetorical")
        assert vent.passed, vent.violation


@needs_openai
class TestSmokeOpenAI:
    @pytest.mark.parametrize("script_name", list(ADVERSARIAL_SCRIPTS.keys()))
    def test_openai_smoke_grade(self, script_name: str):
        report = run_smoke(script_name, OpenAILLMAdapter())
        assert report.smoke.grade in ("A", "B"), (
            f"{script_name}: grade={report.smoke.grade} notes={report.smoke.notes} "
            f"cps={report.smoke.cps_spike_count}"
        )

    @pytest.mark.parametrize("script_name", list(ADVERSARIAL_SCRIPTS.keys()))
    def test_openai_behavior_contracts(self, script_name: str):
        report = run_smoke(script_name, OpenAILLMAdapter())
        assert report.smoke.contract_pass_rate >= 0.5

    @needs_gemini_and_openai
    @pytest.mark.parametrize("script_name", ["semantic_chaos"])
    def test_gemini_openai_parity(self, script_name: str):
        cmp = compare_gemini_vs_openai(script_name)
        assert cmp.grade_parity
        assert cmp.openai.smoke.drift.max_warmth_step <= 0.18
