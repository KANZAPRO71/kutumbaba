"""Counterfactual fix engine tests."""

import pytest

from persona_ai.behavior.engine import decide, decide_with_intent
from persona_ai.core.types import BehaviorInput, IntentDepth, Message, SpeakAction, TurnHistory
from persona_ai.diagnostics.counterfactual import (
    Intervention,
    analyze_counterfactuals,
    simulate_intervention,
)
from persona_ai.diagnostics.failure_taxonomy import (
    FailureClass,
    FailureDomain,
    FailureEvent,
    FailureReport,
    FailureSeverity,
    analyze_smoke,
)
from persona_ai.diagnostics.turn_context import TurnCausalContext, build_turn_context
from persona_ai.behavior.interpret import interpret
from tests.support.stub_llm import StubLLMAdapter
from persona_ai.sim.adversarial_scripts import ADVERSARIAL_SCRIPTS
from persona_ai.sim.drift_harness import DriftMetrics, SessionReport, TurnRecord
from persona_ai.sim.smoke_openai import run_smoke


def _failure_report(events: list[FailureEvent]) -> FailureReport:
    return FailureReport(
        events=events,
        by_domain={},
        by_class={},
        by_severity={},
        structural_count=0,
        degraded_count=0,
        benign_count=0,
        readiness_score=75,
        readiness_grade="v1_stable",
    )


class TestSimulation:
    def test_incompleteness_patch_fixes_defer(self):
        text = "Hmm… sebenarnya…"
        intent = interpret(Message.from_text("user", text), 0)
        assert intent.incompleteness_score >= 0.8
        assert decide(BehaviorInput(message=Message.from_text("user", text))).speak == SpeakAction.DEFER

        # Counterfactual path: simulate pre-fix interpret miss (unicode ellipsis blind spot)
        broken = intent.model_copy(update={"incompleteness_score": 0.0})
        inp = BehaviorInput(message=Message.from_text("user", text))
        baseline = decide_with_intent(inp, broken).speak
        turn = TurnRecord(
            index=0,
            user_text=text,
            speak=baseline,
            effective_warmth=0.6,
            tone_shift="STABLE",
            anchor_baseline=0.6,
            arc_warmth=0.5,
            text="Iyaa, paham.",
            llm_called=False,
            cps_score=0.0,
            context=build_turn_context(broken, decide_with_intent(inp, broken), None, 0.6, 0.6),
        )
        iv = Intervention(
            "raise_incompleteness",
            "interpret",
            "incompleteness_score",
            intent_patch={"incompleteness_score": 0.8},
        )
        cf = simulate_intervention(turn, TurnHistory(), None, iv)
        assert baseline != SpeakAction.DEFER
        assert cf == SpeakAction.DEFER

    def test_intent_need_patch_fixes_respond(self):
        text = "Jangan formal — explain the budget properly"
        intent = interpret(Message.from_text("user", text), 0)
        assert intent.intent_need >= 0.6
        inp = BehaviorInput(message=Message.from_text("user", text))
        assert decide(inp).speak == SpeakAction.RESPOND

        broken = intent.model_copy(update={"intent_need": 0.25, "requires_response": False})
        baseline = decide_with_intent(inp, broken).speak
        turn = TurnRecord(
            index=0,
            user_text=text,
            speak=baseline,
            effective_warmth=0.6,
            tone_shift="STABLE",
            anchor_baseline=0.6,
            arc_warmth=0.5,
            text="ok",
            llm_called=True,
            cps_score=0.0,
            context=build_turn_context(broken, decide_with_intent(inp, broken), None, 0.6, 0.6),
        )
        iv = Intervention(
            "raise_intent_need",
            "interpret",
            "intent_need",
            intent_patch={"intent_need": 0.65, "requires_response": True, "depth": IntentDepth.MODERATE},
        )
        cf = simulate_intervention(turn, TurnHistory(), None, iv)
        assert baseline != SpeakAction.RESPOND
        assert cf == SpeakAction.RESPOND


class TestAnalyze:
    def test_defer_miss_has_minimal_fix(self):
        failure = FailureEvent(
            5, FailureDomain.BDV, FailureClass.BDV_DEFER_MISS,
            FailureSeverity.STRUCTURAL, "defer miss",
        )
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        cf = analyze_counterfactuals(
            FailureReport(
                events=[e for e in report.failure.events if e.failure_class == FailureClass.BDV_DEFER_MISS][:1]
                or [failure],
                by_domain={}, by_class={}, by_severity={},
                structural_count=1, degraded_count=0, benign_count=0,
                readiness_score=75, readiness_grade="v1_stable",
            ),
            report.session,
        )
        assert cf.fixable_count >= 1
        assert cf.nodes[0].minimal_fix is not None
        assert cf.nodes[0].minimal_fix.fixes_failure

    def test_smoke_includes_counterfactual_trace(self):
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        assert report.failure.counterfactual is not None
        assert "Counterfactual Fix Engine" in report.failure.debug_trace
        assert report.failure.readiness_grade == "v2_ready"
        assert report.failure.counterfactual.fixable_count == 0

    def test_counterfactual_trace_on_remaining_failures(self):
        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        assert report.failure.counterfactual.fixable_count == 0


class TestRanking:
    def test_minimal_fix_prefers_low_delta(self):
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        cf = report.failure.counterfactual
        for node in cf.nodes:
            if node.minimal_fix and len(node.results) > 1:
                fixers = [r for r in node.results if r.fixes_failure]
                if fixers:
                    best_delta = min(r.delta_magnitude for r in fixers)
                    assert node.minimal_fix.delta_magnitude == pytest.approx(best_delta, abs=0.01)
