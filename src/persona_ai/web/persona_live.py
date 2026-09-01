"""Persona voice governance — map TurnOutput to Gemini Live actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from persona_ai.core.types import PersonalityProfile, PolicyConstraintsRef, SpeakAction, ToneShift, VoiceDirective
from persona_ai.memory.engine import load_memories_for_prompt
from persona_ai.memory.models import UserMemoryRecord
from persona_ai.runtime import TurnOutput, TurnOverrides
from persona_ai.web.live_mode import LiveModeConfig
from persona_ai.web.voice_instruction import (
    build_engine_directive,
    build_live_engine_instruction,
    build_speak_directive,
)


LIVE_RESPONSE_POLICY = "live_voice"


def live_response_policy(profile: PersonalityProfile) -> str:
    return LiveModeConfig.from_profile(profile).response_policy()


class LiveGovernanceAction(str, Enum):
    """How the Live transport should act after Persona governance."""

    NO_RESPONSE = "no_response"
    SPEAK_GENERATED = "speak_generated"
    SPEAK_LIVE = "speak_live"


class LiveSteerMode(str, Enum):
    """How Persona steers Gemini Live.

    SUPPRESS is gone permanently. Playback mutes only while the user holds
    the floor (user_activity_open). After the user finishes, Gemini must speak.
    """

    STEER = "steer"
    ENGINE = "engine"
    ALLOW = "allow"


@dataclass(frozen=True)
class PersonaLiveDecision:
    action: LiveGovernanceAction
    bdv: str
    text: str | None
    llm_called: bool
    execution_profile: str | None
    pre_llm_ms: float | None = None
    raw_bdv: str | None = None
    effective_bdv: str | None = None


@dataclass(frozen=True)
class LiveGovernancePlan:
    """Steering plan applied to Gemini Live after BDV resolves."""

    steer_mode: LiveSteerMode
    steer_prompt: str | None
    dynamic_instruction: str | None = None


def decide_live_action(output: TurnOutput) -> PersonaLiveDecision:
    """Translate PersonaRuntime turn output into a Live transport decision."""
    bdv = output.bdv
    action_name = bdv.speak.value if bdv else SpeakAction.RESPOND.value
    raw_bdv = getattr(output, "raw_bdv", None)
    effective_bdv = getattr(output, "effective_bdv", None) or bdv
    raw_action = raw_bdv.speak.value if raw_bdv else action_name
    effective_action = effective_bdv.speak.value if effective_bdv else action_name
    profile = output.trace.execution_profile if output.trace else None
    pre_llm = output.trace.timing.pre_llm_ms if output.trace and output.trace.timing else None

    if action_name in (SpeakAction.SILENCE.value, SpeakAction.DEFER.value):
        return PersonaLiveDecision(
            action=LiveGovernanceAction.NO_RESPONSE,
            bdv=action_name,
            text=None,
            llm_called=output.llm_called,
            execution_profile=profile,
            pre_llm_ms=pre_llm,
            raw_bdv=raw_action,
            effective_bdv=effective_action,
        )

    if output.text:
        return PersonaLiveDecision(
            action=LiveGovernanceAction.SPEAK_GENERATED,
            bdv=action_name,
            text=output.text,
            llm_called=output.llm_called,
            execution_profile=profile,
            pre_llm_ms=pre_llm,
            raw_bdv=raw_action,
            effective_bdv=effective_action,
        )

    return PersonaLiveDecision(
        action=LiveGovernanceAction.SPEAK_LIVE,
        bdv=action_name,
        text=None,
        llm_called=output.llm_called,
        execution_profile=profile,
        pre_llm_ms=pre_llm,
        raw_bdv=raw_action,
        effective_bdv=effective_action,
    )


def plan_live_governance(
    output: TurnOutput,
    decision: PersonaLiveDecision,
    profile: PersonalityProfile,
    history: list | None = None,
    *,
    live_mode: LiveModeConfig | None = None,
    dialect: str | None = None,
    post_call: dict | None = None,
    user_memories: list[UserMemoryRecord] | None = None,
) -> LiveGovernancePlan:
    """Build Gemini Live steering from Persona turn output + conversation transcript."""
    mode_cfg = live_mode or LiveModeConfig.from_profile(profile)
    if mode_cfg.is_natural:
        return _plan_natural_governance(output, decision, profile, history, dialect=dialect)
    return _plan_governed_governance(
        output,
        decision,
        profile,
        history,
        dialect=dialect,
        post_call=post_call,
        user_memories=user_memories,
    )


def _plan_natural_governance(
    output: TurnOutput,
    decision: PersonaLiveDecision,
    profile: PersonalityProfile,
    history: list | None,
    *,
    dialect: str | None = None,
) -> LiveGovernancePlan:
    """ChatGPT-like S2S — Gemini answers the user's turn. Never canned ACK."""
    if output.policy_input_blocked and decision.text:
        return LiveGovernancePlan(
            steer_mode=LiveSteerMode.STEER,
            steer_prompt=build_speak_directive(
                bdv=decision.bdv, text=decision.text, ack_only=False, dialect=dialect
            ),
        )

    return LiveGovernancePlan(
        steer_mode=LiveSteerMode.ALLOW,
        steer_prompt=None,
    )


def _plan_governed_governance(
    output: TurnOutput,
    decision: PersonaLiveDecision,
    profile: PersonalityProfile,
    history: list | None,
    *,
    dialect: str | None = None,
    post_call: dict | None = None,
    user_memories: list[UserMemoryRecord] | None = None,
) -> LiveGovernancePlan:
    """Persona-first — ENGINE steer before every governed reply."""
    thread = list(history or [])
    if decision.action == LiveGovernanceAction.NO_RESPONSE:
        return LiveGovernancePlan(
            steer_mode=LiveSteerMode.ALLOW,
            steer_prompt=None,
        )

    if decision.action == LiveGovernanceAction.SPEAK_GENERATED and decision.text:
        if output.policy_input_blocked:
            return LiveGovernancePlan(
                steer_mode=LiveSteerMode.STEER,
                steer_prompt=build_speak_directive(
                    bdv=decision.bdv, text=decision.text, ack_only=False, dialect=dialect
                ),
            )
        voice = output.voice if isinstance(output.voice, VoiceDirective) else None
        if voice is None:
            voice = VoiceDirective(
                speak=SpeakAction.RESPOND,
                effective_warmth=profile.warmth,
                max_words=40,
                max_sentences=2,
                question_budget=0,
                tone_shift=ToneShift.STABLE,
            )
        engine = build_live_engine_instruction(
            profile,
            voice,
            policy_constraints=_policy_constraints_from_output(output),
            history=thread,
            dialect=dialect,
            post_call=post_call,
            user_memories=user_memories,
        )
        return LiveGovernancePlan(
            steer_mode=LiveSteerMode.ENGINE,
            steer_prompt=build_engine_directive(engine, dialect=dialect),
            dynamic_instruction=engine,
        )

    voice = output.voice if isinstance(output.voice, VoiceDirective) else None
    if voice is not None:
        policy = _policy_constraints_from_output(output)
        engine = build_live_engine_instruction(
            profile,
            voice,
            policy_constraints=policy,
            history=thread,
            dialect=dialect,
            post_call=post_call,
            user_memories=user_memories,
        )
        return LiveGovernancePlan(
            steer_mode=LiveSteerMode.ENGINE,
            steer_prompt=build_engine_directive(engine, dialect=dialect),
            dynamic_instruction=engine,
        )

    # RESPOND without pre-rendered text — still govern via ENGINE, never raw Gemini default
    engine = build_live_engine_instruction(
        profile,
        VoiceDirective(
            speak=SpeakAction.RESPOND,
            effective_warmth=profile.warmth,
            max_words=40,
            max_sentences=2,
            question_budget=0,
            tone_shift=ToneShift.STABLE,
        ),
        history=thread,
        dialect=dialect,
        post_call=post_call,
        user_memories=user_memories,
    )
    return LiveGovernancePlan(
        steer_mode=LiveSteerMode.ENGINE,
        steer_prompt=build_engine_directive(engine, dialect=dialect),
        dynamic_instruction=engine,
    )


def session_overrides(runtime, session_id: str) -> TurnOverrides:
    """Load session context for ephemeral (partial) BDV without persisting."""
    session = runtime.session_store.load(session_id)
    if session is None:
        return TurnOverrides()
    return TurnOverrides(
        history=session.turn_history,
        anchor=session.anchor,
        messages=session.messages,
    )


def load_user_memories() -> list[UserMemoryRecord]:
    return load_memories_for_prompt()


def load_session_messages(runtime, session_id: str) -> list:
    session = runtime.session_store.load(session_id)
    if session is None:
        return []
    return list(session.messages)


def load_session_post_call(runtime, session_id: str) -> dict | None:
    session = runtime.session_store.load(session_id)
    if session is None:
        return None
    post_call = session.post_call
    return post_call if isinstance(post_call, dict) else None


def load_session_context(runtime, session_id: str) -> tuple[list, dict | None]:
    session = runtime.session_store.load(session_id)
    if session is None:
        return [], None
    post_call = session.post_call if isinstance(session.post_call, dict) else None
    return list(session.messages), post_call


def governance_payload(
    decision: PersonaLiveDecision,
    *,
    plan: LiveGovernancePlan | None = None,
    partial: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "governance_preview" if partial else "governance",
        "action": decision.action.value,
        "bdv": decision.bdv,
        "raw_bdv": decision.raw_bdv,
        "effective_bdv": decision.effective_bdv,
        "text": decision.text,
        "llm_called": decision.llm_called,
        "execution_profile": decision.execution_profile,
        "pre_llm_ms": decision.pre_llm_ms,
        "partial": partial,
    }
    if plan is not None and not partial:
        payload["steer_mode"] = plan.steer_mode.value
    elif plan is not None and partial:
        payload["steer_mode"] = plan.steer_mode.value
    if partial:
        payload.pop("action", None)
    return payload


def _policy_constraints_from_output(output: TurnOutput) -> PolicyConstraintsRef | None:
    constraints = getattr(output, "policy_constraints", None)
    return constraints if isinstance(constraints, PolicyConstraintsRef) else None
