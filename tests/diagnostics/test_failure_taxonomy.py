"""Failure taxonomy layer tests."""

from persona_ai.core.types import SpeakAction
from persona_ai.diagnostics.failure_taxonomy import (
    FailureClass,
    FailureDomain,
    FailureSeverity,
    analyze_session,
    analyze_smoke,
    classify_contract_failure,
    format_debug_trace,
)
from persona_ai.sim.adversarial_scripts import ADVERSARIAL_SCRIPTS
from persona_ai.sim.drift_harness import DriftMetrics, SessionReport, TurnRecord
from persona_ai.sim.smoke_openai import run_smoke
from persona_ai.llm.adapter import score_cps
from tests.support.stub_llm import StubLLMAdapter


def _turn(**kwargs) -> TurnRecord:
    defaults = dict(
        index=0,
        user_text="hi",
        speak=SpeakAction.RESPOND,
        effective_warmth=0.6,
        tone_shift="STABLE",
        anchor_baseline=0.6,
        arc_warmth=0.5,
        text="Hello.",
        llm_called=True,
        cps_score=0.0,
    )
    defaults.update(kwargs)
    return TurnRecord(**defaults)


def _clean_metrics() -> DriftMetrics:
    return DriftMetrics(
        turn_count=10,
        warmth_values=[0.6] * 10,
        anchor_values=[0.6] * 10,
        max_warmth_step=0.05,
        warmth_range=0.08,
        anchor_range=0.06,
        warmth_std=0.02,
        speak_counts={"RESPOND": 5, "ACK_ONLY": 3, "SILENCE": 2},
        max_same_speak_streak=3,
        silence_ratio=0.2,
        mechanical_score=0.1,
        identity_stable=True,
        grade="A",
    )


class TestClassifiers:
    def test_clean_session_high_readiness(self):
        session = SessionReport("clean", [_turn()], _clean_metrics())
        report = analyze_session(session)
        assert report.readiness_score >= 90
        assert report.readiness_grade == "v2_ready"
        assert report.structural_count == 0

    def test_cps_spike_classified_llm(self):
        score, hits = score_cps("Ada lagi yang bisa saya bantu?")
        turn = _turn(cps_score=score, cps_hits=hits, text="Ada lagi yang bisa saya bantu?")
        report = analyze_session(SessionReport("cps", [turn], _clean_metrics()))
        classes = [e.failure_class for e in report.events]
        assert FailureClass.LLM_CPS_SPIKE in classes
        assert any(e.domain == FailureDomain.LLM for e in report.events)

    def test_warmth_jump_coherence(self):
        t0 = _turn(index=0, effective_warmth=0.55)
        t1 = _turn(index=1, effective_warmth=0.82)
        report = analyze_session(SessionReport("jump", [t0, t1], _clean_metrics()))
        assert any(e.failure_class == FailureClass.COHERENCE_WARMTH_JUMP for e in report.events)

    def test_contract_bdv_silence_miss(self):
        turn = _turn(speak=SpeakAction.RESPOND, text="Should not speak")
        event = classify_contract_failure(
            0, "closure", "expected SILENCE, got RESPOND", turn, SpeakAction.SILENCE
        )
        assert event.domain == FailureDomain.BDV
        assert event.failure_class == FailureClass.BDV_SILENCE_MISS
        assert event.severity == FailureSeverity.STRUCTURAL

    def test_contract_llm_overreach(self):
        turn = _turn(speak=SpeakAction.SILENCE, text="Oops I spoke")
        event = classify_contract_failure(
            0, "closure", "expected no output, got: 'Oops'", turn, SpeakAction.SILENCE
        )
        assert event.failure_class == FailureClass.LLM_OVERREACH

    def test_debug_trace_actionable(self):
        session = SessionReport("x", [_turn()], _clean_metrics())
        trace = format_debug_trace(analyze_session(session))
        assert "readiness=" in trace


class TestSmokeIntegration:
    def test_mock_smoke_readiness(self):
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        assert report.failure is not None
        assert report.failure.readiness_score >= 65
        assert report.failure.readiness_grade in ("v2_ready", "v1_stable")

    def test_smoke_analyze_with_specs(self):
        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        failure = report.failure
        assert failure is not None
        # Passing run should have few or no structural failures
        assert failure.structural_count <= 1
