"""Tests for Persona Live governance mapping."""

from __future__ import annotations

from persona_ai.core.types import (
    BehaviorDirectiveVector,
    Message,
    PersonalityProfile,
    SpeakAction,
    ToneShift,
    TurnHistory,
    VoiceDirective,
)
from persona_ai.personality.preset import load_default_preset
from persona_ai.runtime import TurnOutput, TurnTrace, TurnTiming
from persona_ai.web.live_mode import LiveModeConfig
from persona_ai.web.persona_live import (
    LiveGovernanceAction,
    LiveSteerMode,
    decide_live_action,
    governance_payload,
    plan_live_governance,
)
from persona_ai.web.voice_instruction import (
    build_engine_directive,
    build_live_voice_instruction,
    build_speak_directive,
)


def _output(
    *,
    speak: SpeakAction,
    text: str | None = None,
    llm_called: bool = False,
    voice: VoiceDirective | None = None,
) -> TurnOutput:
    bdv = BehaviorDirectiveVector(speak=speak, requires_llm=speak == SpeakAction.RESPOND)
    if voice is None and speak == SpeakAction.RESPOND:
        voice = VoiceDirective(
            speak=speak,
            effective_warmth=0.7,
            max_words=40,
            max_sentences=2,
            question_budget=0,
            tone_shift=ToneShift.STABLE,
        )
    trace = TurnTrace(
        session_id="s1",
        turn_index=1,
        bdv_action=speak.value,
        execution_profile="standard",
        llm_called=llm_called,
        persistence_ok=True,
        timing=TurnTiming(pre_llm_ms=12.5, llm_ms=None, post_llm_ms=0.0, total_ms=12.5),
    )
    return TurnOutput(
        voice=voice or object(),
        text=text,
        llm_called=llm_called,
        cps_score=0.0,
        cps_hits=[],
        bdv=bdv,
        trace=trace,
    )


class TestDecideLiveAction:
    def test_silence_no_response(self):
        decision = decide_live_action(_output(speak=SpeakAction.SILENCE))
        assert decision.action == LiveGovernanceAction.NO_RESPONSE
        assert decision.text is None

    def test_defer_no_response(self):
        decision = decide_live_action(_output(speak=SpeakAction.DEFER))
        assert decision.action == LiveGovernanceAction.NO_RESPONSE

    def test_ack_speak_generated(self):
        decision = decide_live_action(_output(speak=SpeakAction.ACK_ONLY, text="Berat ya."))
        assert decision.action == LiveGovernanceAction.SPEAK_GENERATED
        assert decision.text == "Berat ya."

    def test_respond_speak_generated(self):
        decision = decide_live_action(
            _output(speak=SpeakAction.RESPOND, text="Besok jam 9.", llm_called=True)
        )
        assert decision.action == LiveGovernanceAction.SPEAK_GENERATED
        assert decision.llm_called is True

    def test_governance_payload(self):
        decision = decide_live_action(_output(speak=SpeakAction.SILENCE))
        payload = governance_payload(decision)
        assert payload["type"] == "governance"
        assert payload["action"] == "no_response"
        assert payload["bdv"] == "SILENCE"
        assert payload["pre_llm_ms"] == 12.5

    def test_always_answer_exposes_raw_and_effective_bdv(self):
        raw = BehaviorDirectiveVector(speak=SpeakAction.DEFER)
        effective = BehaviorDirectiveVector(speak=SpeakAction.ACK_ONLY)
        out = TurnOutput(
            voice=object(),
            text="Lanjut, aku dengerin.",
            llm_called=False,
            cps_score=0.0,
            cps_hits=[],
            bdv=effective,
            raw_bdv=raw,
            effective_bdv=effective,
        )

        decision = decide_live_action(out)
        payload = governance_payload(decision)

        assert decision.action == LiveGovernanceAction.SPEAK_GENERATED
        assert payload["raw_bdv"] == "DEFER"
        assert payload["effective_bdv"] == "ACK_ONLY"
        assert payload["text"] == "Lanjut, aku dengerin."


_GOVERNED = LiveModeConfig(mode="governed")


class TestPlanLiveGovernance:
    def test_silence_allows_s2s_reply(self):
        profile = load_default_preset()
        output = _output(speak=SpeakAction.SILENCE)
        decision = decide_live_action(output)
        plan = plan_live_governance(output, decision, profile, live_mode=_GOVERNED)
        assert plan.steer_mode == LiveSteerMode.ALLOW

    def test_ack_uses_engine_not_canned_line(self):
        profile = load_default_preset()
        output = _output(speak=SpeakAction.ACK_ONLY, text="Hmm, berat ya.")
        decision = decide_live_action(output)
        plan = plan_live_governance(output, decision, profile, live_mode=_GOVERNED)
        assert plan.steer_mode == LiveSteerMode.ENGINE
        assert "PERSONA_GOVERNANCE" in (plan.steer_prompt or "")
        assert "Hmm, berat ya." not in (plan.steer_prompt or "")

    def test_respond_with_voice_engine(self):
        profile = load_default_preset()
        voice = VoiceDirective(
            speak=SpeakAction.RESPOND,
            effective_warmth=0.7,
            max_words=30,
            max_sentences=2,
            question_budget=0,
            tone_shift=ToneShift.STABLE,
        )
        output = _output(speak=SpeakAction.RESPOND, text="Oke.", llm_called=True, voice=voice)
        decision = decide_live_action(output)
        plan = plan_live_governance(output, decision, profile, live_mode=_GOVERNED)
        assert plan.steer_mode == LiveSteerMode.ENGINE
        assert plan.steer_prompt is not None
        assert "Oke." not in plan.steer_prompt
        assert "Spoken action this turn: RESPOND" in plan.steer_prompt

    def test_blocked_input_speaks_exact_fallback(self):
        profile = load_default_preset()
        output = _output(speak=SpeakAction.RESPOND, text="Maaf, itu tidak bisa.")
        output.policy_input_blocked = True
        decision = decide_live_action(output)
        plan = plan_live_governance(output, decision, profile, live_mode=_GOVERNED)
        assert plan.steer_mode == LiveSteerMode.STEER
        assert "Maaf, itu tidak bisa." in (plan.steer_prompt or "")

    def test_speak_live_never_allows_ungoverned_gemini(self):
        profile = load_default_preset()
        output = _output(speak=SpeakAction.RESPOND, text=None, voice=object())
        decision = decide_live_action(output)
        assert decision.action == LiveGovernanceAction.SPEAK_LIVE
        plan = plan_live_governance(output, decision, profile, live_mode=_GOVERNED)
        assert plan.steer_mode == LiveSteerMode.ENGINE
        assert plan.steer_prompt is not None
        assert "PERSONA_GOVERNANCE" in plan.steer_prompt

    def test_engine_steer_includes_prior_conversation(self):
        profile = load_default_preset()
        output = _output(speak=SpeakAction.RESPOND, text=None)
        decision = decide_live_action(output)
        plan = plan_live_governance(
            output,
            decision,
            profile,
            history=[
                Message.from_text("user", "ada mobil Honda di tahunnya M. M itu apa?"),
            ],
            live_mode=_GOVERNED,
        )
        assert "ada mobil Honda" in (plan.steer_prompt or "")
        assert "Conversation so far:" in (plan.steer_prompt or "")

    def test_natural_respond_allows_s2s(self):
        profile = load_default_preset()
        output = _output(speak=SpeakAction.RESPOND, text=None)
        decision = decide_live_action(output)
        plan = plan_live_governance(output, decision, profile)
        assert plan.steer_mode == LiveSteerMode.ALLOW
        assert plan.steer_prompt is None

    def test_natural_silence_still_allows_s2s(self):
        profile = load_default_preset()
        output = _output(speak=SpeakAction.SILENCE)
        decision = decide_live_action(output)
        plan = plan_live_governance(output, decision, profile)
        assert plan.steer_mode == LiveSteerMode.ALLOW
        assert plan.steer_prompt is None

    def test_natural_ack_allows_full_s2s(self):
        profile = load_default_preset()
        output = _output(speak=SpeakAction.ACK_ONLY, text="Iyaa, paham.")
        decision = decide_live_action(output)
        plan = plan_live_governance(output, decision, profile)
        assert plan.steer_mode == LiveSteerMode.ALLOW
        assert plan.steer_prompt is None


class TestVoiceDirectives:
    def test_natural_baseline_is_short(self):
        profile = load_default_preset()
        text = build_live_voice_instruction(profile)
        assert "ChatGPT voice" in text
        assert "PERSONA_GOVERNANCE" not in text
        assert "Turn protocol" not in text
        assert "Agent Handbook" not in text

    def test_governed_baseline_includes_governance(self):
        profile = load_default_preset()
        profile = profile.model_copy(update={"preset_id": "default_companion"})
        from persona_ai.web.voice_instruction import _build_governed_live_instruction

        text = _build_governed_live_instruction(profile)
        assert "PERSONA_GOVERNANCE" in text
        assert "Turn protocol" in text

    def test_speak_directive_ack(self):
        text = build_speak_directive(bdv="ACK_ONLY", text="Iya.", ack_only=True)
        assert "Iya." in text
        assert "One short sentence" in text

    def test_engine_directive(self):
        assert "ENGINE" in build_engine_directive("Max words: 20")

    def test_partial_preview_payload(self):
        decision = decide_live_action(_output(speak=SpeakAction.DEFER))
        plan = plan_live_governance(
            _output(speak=SpeakAction.DEFER),
            decision,
            load_default_preset(),
        )
        payload = governance_payload(decision, plan=plan, partial=True)
        assert payload["type"] == "governance_preview"
        assert payload["bdv"] == "DEFER"
        assert "action" not in payload
        assert "suppress_audio" not in payload
