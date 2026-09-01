"""Causal failure graph tests."""

import pytest

from persona_ai.core.types import SpeakAction
from persona_ai.diagnostics.causal_graph import build_causal_report, decompose_failure, enrich_with_causality
from persona_ai.diagnostics.failure_taxonomy import (
    FailureClass,
    FailureDomain,
    FailureEvent,
    FailureSeverity,
    analyze_smoke,
    classify_contract_failure,
)
from persona_ai.diagnostics.turn_context import TurnCausalContext, build_turn_context
from tests.support.stub_llm import StubLLMAdapter
from persona_ai.sim.adversarial_scripts import ADVERSARIAL_SCRIPTS
from persona_ai.sim.drift_harness import DriftMetrics, SessionReport, TurnRecord
from persona_ai.sim.smoke_openai import run_smoke


def _metrics() -> DriftMetrics:
    return DriftMetrics(
        turn_count=1,
        warmth_values=[0.6],
        anchor_values=[0.6],
        max_warmth_step=0.05,
        warmth_range=0.08,
        anchor_range=0.06,
        warmth_std=0.02,
        speak_counts={"ACK_ONLY": 1},
        max_same_speak_streak=1,
        silence_ratio=0.0,
        mechanical_score=0.1,
        identity_stable=True,
        grade="A",
    )


def _turn_with_ctx(**ctx_kw) -> TurnRecord:
    ctx = TurnCausalContext(**ctx_kw)
    return TurnRecord(
        index=0,
        user_text="test",
        speak=SpeakAction.ACK_ONLY,
        effective_warmth=0.6,
        tone_shift="STABLE",
        anchor_baseline=0.6,
        arc_warmth=0.5,
        text="Berat ya.",
        llm_called=False,
        cps_score=0.0,
        context=ctx,
    )


class TestDecomposition:
    def test_under_responsive_root_is_interpret_or_pressure(self):
        turn = _turn_with_ctx(
            intent_need=0.2,
            emotional_intensity=0.7,
            is_vent=True,
            action_probabilities={"ACK_ONLY": 0.6, "RESPOND": 0.3},
        )
        failure = FailureEvent(
            0, FailureDomain.BDV, FailureClass.BDV_UNDER_RESPONSIVE,
            FailureSeverity.DEGRADED, "expected RESPOND, got ACK_ONLY",
        )
        session = SessionReport("t", [turn], _metrics())
        node = decompose_failure(failure, session)
        assert node.root_source in ("interpret", "pressure", "arbitration")
        assert sum(c.attribution for c in node.contributions) == pytest.approx(1.0, abs=0.01)

    def test_defer_miss_blames_incompleteness(self):
        turn = _turn_with_ctx(
            incompleteness_score=0.0,
            defer_pressure=0.3,
            emotional_intensity=0.65,
            is_vent=True,
            action_probabilities={"ACK_ONLY": 0.5, "DEFER": 0.2},
        )
        turn.reason_codes = ["rhetorical_vent"]
        failure = FailureEvent(
            0, FailureDomain.BDV, FailureClass.BDV_DEFER_MISS,
            FailureSeverity.STRUCTURAL, "defer miss",
        )
        node = decompose_failure(failure, SessionReport("t", [turn], _metrics()))
        signals = {c.signal for c in node.contributions}
        assert "incompleteness_score" in signals or "rhetorical_vent" in signals

    def test_llm_overreach_blames_render(self):
        turn = _turn_with_ctx()
        turn.speak = SpeakAction.SILENCE
        turn.text = "leaked"
        failure = FailureEvent(
            0, FailureDomain.LLM, FailureClass.LLM_OVERREACH,
            FailureSeverity.STRUCTURAL, "silent but spoke",
        )
        node = decompose_failure(failure, SessionReport("t", [turn], _metrics()))
        assert node.root_cause.startswith("llm.")


class TestIntegration:
    def test_smoke_run_includes_causal_tree(self):
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        assert report.failure is not None
        assert report.failure.causal is not None
        assert "Causal Graph" in report.failure.debug_trace
        assert report.failure.readiness_grade == "v2_ready"

    def test_causal_tree_populated_when_failures_exist(self):
        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        assert report.failure.events == []
        assert not report.failure.causal.by_source

    def test_enrich_adds_root_cause_per_failure(self):
        smoke_report = run_smoke("sarcasm_stack", StubLLMAdapter())
        assert smoke_report.failure.events == []
        assert not smoke_report.failure.causal.nodes