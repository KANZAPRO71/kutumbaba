"""PersonaRuntime — official v1 application entry point."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from persona_ai.behavior.engine import decide, execution_profile
from persona_ai.coherence.bind import IdentityAnchor, bind, update_anchor
from persona_ai.core.types import (
    BehaviorDirectiveVector,
    BehaviorInput,
    Message,
    PersonalityProfile,
    PolicyConstraintsRef,
    QuestionPolicy,
    ResponseLength,
    SpeakAction,
    TurnHistory,
)
from persona_ai.llm.adapter import LLMAdapter, default_adapter, render, score_cps
from persona_ai.llm.prompt import strip_trailing_questions
from persona_ai.personality.apply import apply
from persona_ai.personality.preset import load_default_preset
from persona_ai.web.time_awareness import TimeAwarenessConfig
from persona_ai.policy.engine import PolicyEngine
from persona_ai.policy.types import PolicyResult
from persona_ai.session.models import SessionState
from persona_ai.session.store import InMemorySessionStore, SessionStore, SQLiteSessionStore, default_db_path
from persona_ai.session.updates import (
    advance_arc,
    append_messages,
    reason_codes_from_bdv,
    update_turn_history,
)


@dataclass
class TurnTiming:
    """Pre-LLM governance latency — excludes network LLM time."""

    pre_llm_ms: float
    llm_ms: float | None
    post_llm_ms: float
    total_ms: float


@dataclass
class TurnTrace:
    session_id: str
    turn_index: int
    bdv_action: str
    execution_profile: str
    llm_called: bool
    persistence_ok: bool
    raw_bdv_action: str | None = None
    effective_bdv_action: str | None = None
    response_policy: str = "governed"
    policy_input_blocked: bool = False
    policy_post_status: str | None = None
    policy_rewrite_count: int = 0
    timing: TurnTiming | None = None


@dataclass
class TurnOverrides:
    """Optional one-shot overrides for pipeline_v0 compatibility."""

    history: TurnHistory | None = None
    anchor: IdentityAnchor | None = None
    messages: list[Message] | None = None


@dataclass
class TurnOutput:
    voice: object
    text: str | None
    llm_called: bool
    cps_score: float
    cps_hits: list[str]
    bdv: object | None = None
    raw_bdv: object | None = None
    effective_bdv: object | None = None
    anchor: IdentityAnchor | None = None
    trace: TurnTrace | None = None
    policy_result: PolicyResult | None = None
    policy_input_blocked: bool = False
    policy_constraints: PolicyConstraintsRef | None = None
    timing: TurnTiming | None = None


class PersonaRuntime:
    """Official v1 entry point — load session, run pipeline, commit session."""

    def __init__(
        self,
        session_store: SessionStore | None = None,
        personality_profile: PersonalityProfile | None = None,
        llm_adapter: LLMAdapter | None = None,
        policy_engine: PolicyEngine | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        if session_store is None:
            session_store = SQLiteSessionStore(db_path or default_db_path())
        self._store = session_store
        self._profile = personality_profile or load_default_preset()
        self._adapter = llm_adapter or default_adapter()
        self._policy = policy_engine or PolicyEngine()
        self._live_security: object | None = None
        self.last_trace: TurnTrace | None = None

    def configure_live_security(self, cfg: object) -> None:
        """Apply Retell Security settings — policy guardrails + storage filtering."""
        self._live_security = cfg
        to_policy = getattr(cfg, "to_policy_context", None)
        if callable(to_policy):
            self._policy = PolicyEngine(to_policy())

    def _save_session(self, session: SessionState) -> None:
        stored = session
        if self._live_security is not None:
            filt = getattr(self._live_security, "filter_session_for_storage", None)
            if callable(filt):
                stored = filt(session)
        self._store.save(stored)

    @property
    def session_store(self) -> SessionStore:
        return self._store

    def record_spoken_reply(self, session_id: str, text: str) -> None:
        """Persist assistant Live audio transcript so a reconnect can resume."""
        stripped = text.strip()
        if not stripped:
            return
        session = self._store.load(session_id)
        if session is None:
            session = SessionState.new(session_id, profile_warmth=self._profile.warmth)
        messages = list(session.messages)
        last = messages[-1] if messages else None
        if last and last.role == "assistant":
            prev = last.text.strip()
            if stripped == prev:
                return
            if stripped.startswith(prev) or prev.startswith(stripped):
                if len(stripped) >= len(prev):
                    messages[-1] = Message.from_text("assistant", stripped)
                    self._save_session(
                        session.model_copy(
                            update={"messages": messages, "updated_at": _utc_now()}
                        )
                    )
                return
            # Live ASR revision — replace instead of duplicating assistant lines.
            messages[-1] = Message.from_text("assistant", stripped)
            self._save_session(
                session.model_copy(update={"messages": messages, "updated_at": _utc_now()})
            )
            return
        messages.append(Message.from_text("assistant", stripped))
        self._save_session(
            session.model_copy(update={"messages": messages, "updated_at": _utc_now()})
        )

    def record_post_call_data(self, session_id: str, payload: dict) -> None:
        """Persist Retell-style post-call extraction on the session."""
        session = self._store.load(session_id)
        if session is None:
            session = SessionState.new(session_id, profile_warmth=self._profile.warmth)
        self._save_session(
            session.model_copy(
                update={"post_call": payload, "updated_at": _utc_now()}
            )
        )

    @property
    def personality_profile(self) -> PersonalityProfile:
        return self._profile

    @property
    def llm_adapter(self) -> LLMAdapter:
        return self._adapter

    @property
    def policy_engine(self) -> PolicyEngine:
        return self._policy

    def process_turn(
        self,
        session_id: str,
        user_text: str,
        *,
        overrides: TurnOverrides | None = None,
        persist: bool = True,
        voice_pause_ms: int | None = None,
        channel: str = "voice",
        response_policy: str = "governed",
        generate_text: bool = True,
    ) -> TurnOutput:
        if persist:
            return self._process_persisted(
                session_id,
                user_text,
                voice_pause_ms=voice_pause_ms,
                channel=channel,
                response_policy=response_policy,
                generate_text=generate_text,
            )
        return self._process_ephemeral(
            session_id,
            user_text,
            overrides=overrides or TurnOverrides(),
            voice_pause_ms=voice_pause_ms,
            channel=channel,
            response_policy=response_policy,
            generate_text=generate_text,
        )

    def _process_persisted(
        self,
        session_id: str,
        user_text: str,
        *,
        voice_pause_ms: int | None = None,
        channel: str = "voice",
        response_policy: str = "governed",
        generate_text: bool = True,
    ) -> TurnOutput:
        session = self._store.load(session_id)
        if session is None:
            session = SessionState.new(session_id, profile_warmth=self._profile.warmth)

        persistence_ok = False
        output: TurnOutput | None = None
        next_session = session
        try:
            output, next_session = self._run_pipeline(
                session=session,
                user_text=user_text,
                voice_pause_ms=voice_pause_ms,
                channel=channel,
                response_policy=response_policy,
                generate_text=generate_text,
            )
            self._save_session(next_session)
            persistence_ok = True
        except Exception as exc:
            trace = TurnTrace(
                session_id=session_id,
                turn_index=session.turn_index,
                bdv_action=output.bdv.speak.value if output and output.bdv else "error",
                execution_profile=execution_profile(output.bdv) if output and output.bdv else "error",
                llm_called=output.llm_called if output else False,
                persistence_ok=False,
                raw_bdv_action=(
                    output.raw_bdv.speak.value if output and output.raw_bdv else None
                ),
                effective_bdv_action=(
                    output.effective_bdv.speak.value if output and output.effective_bdv else None
                ),
                response_policy=response_policy,
                policy_input_blocked=output.policy_input_blocked if output else False,
                policy_post_status=(
                    output.policy_result.status.value if output and output.policy_result else None
                ),
                policy_rewrite_count=(
                    output.policy_result.rewrite_count if output and output.policy_result else 0
                ),
                timing=output.timing if output else None,
            )
            self.last_trace = trace
            if output is not None:
                output.trace = trace
            raise exc
        else:
            trace = TurnTrace(
                session_id=session_id,
                turn_index=next_session.turn_index,
                bdv_action=output.bdv.speak.value if output.bdv else "unknown",
                execution_profile=execution_profile(output.bdv) if output.bdv else "unknown",
                llm_called=output.llm_called,
                persistence_ok=persistence_ok,
                raw_bdv_action=output.raw_bdv.speak.value if output.raw_bdv else None,
                effective_bdv_action=(
                    output.effective_bdv.speak.value if output.effective_bdv else None
                ),
                response_policy=response_policy,
                policy_input_blocked=output.policy_input_blocked,
                policy_post_status=(
                    output.policy_result.status.value if output.policy_result else None
                ),
                policy_rewrite_count=(
                    output.policy_result.rewrite_count if output.policy_result else 0
                ),
                timing=output.timing,
            )
            self.last_trace = trace
            output.trace = trace
            return output

    def _process_ephemeral(
        self,
        session_id: str,
        user_text: str,
        *,
        overrides: TurnOverrides,
        voice_pause_ms: int | None = None,
        channel: str = "voice",
        response_policy: str = "governed",
        generate_text: bool = True,
    ) -> TurnOutput:
        from persona_ai.arc import store as arc_store

        arc = arc_store.load(session_id)
        session = SessionState(
            session_id=session_id,
            arc=arc,
            anchor=overrides.anchor or IdentityAnchor(session_tone_baseline=self._profile.warmth),
            turn_history=overrides.history or TurnHistory(),
            messages=list(overrides.messages or []),
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )

        output, _ = self._run_pipeline(
            session=session,
            user_text=user_text,
            voice_pause_ms=voice_pause_ms,
            commit_state=False,
            channel=channel,
            response_policy=response_policy,
            generate_text=generate_text,
        )

        trace = TurnTrace(
            session_id=session_id,
            turn_index=session.turn_index + 1,
            bdv_action=output.bdv.speak.value if output.bdv else "unknown",
            execution_profile=execution_profile(output.bdv) if output.bdv else "unknown",
            llm_called=output.llm_called,
            persistence_ok=False,
            raw_bdv_action=output.raw_bdv.speak.value if output.raw_bdv else None,
            effective_bdv_action=(
                output.effective_bdv.speak.value if output.effective_bdv else None
            ),
            response_policy=response_policy,
            policy_input_blocked=output.policy_input_blocked,
            policy_post_status=output.policy_result.status.value if output.policy_result else None,
            policy_rewrite_count=output.policy_result.rewrite_count if output.policy_result else 0,
            timing=output.timing,
        )
        self.last_trace = trace
        output.trace = trace
        return output

    def _run_pipeline(
        self,
        *,
        session: SessionState,
        user_text: str,
        voice_pause_ms: int | None = None,
        commit_state: bool = True,
        channel: str = "voice",
        response_policy: str = "governed",
        generate_text: bool = True,
    ) -> tuple[TurnOutput, SessionState]:
        t0 = time.perf_counter()
        pre = self._policy.pre_check(user_text)

        policy_signals = list(pre.tier0_signals)

        inp = BehaviorInput(
            message=Message.from_text("user", user_text),
            history=session.turn_history,
            arc=session.arc,
            voice_pause_ms=voice_pause_ms,
            policy_signals=policy_signals,
        )
        raw_bdv = decide(inp)
        bdv = _cap_question_budget(_apply_response_policy(raw_bdv, response_policy), self._profile)
        expr = apply(self._profile, bdv, session.arc, execution_profile(bdv))
        voice = bind(bdv, expr, self._profile, session.arc, session.anchor)

        updated_anchor = session.anchor
        if session.anchor is not None:
            updated_anchor = update_anchor(session.anchor, voice.effective_warmth)

        text: str | None = None
        llm_called = False
        cps_score = 0.0
        cps_hits: list[str] = []
        policy_result: PolicyResult | None = None
        llm_constraints = _llm_constraints_ref(pre.constraints)

        if bdv.speak in (SpeakAction.SILENCE, SpeakAction.DEFER):
            pass
        elif pre.input_blocked:
            text = pre.fallback_text
            llm_called = False
        elif not generate_text:
            text = None
            llm_called = False
        else:
            t_pre_llm = time.perf_counter()
            time_cfg = TimeAwarenessConfig.from_profile(self._profile)
            draft = render(
                voice,
                user_text,
                self._adapter,
                history=session.messages,
                policy_constraints=llm_constraints,
                agent_timezone=time_cfg.timezone,
                language=self._profile.default_language or "id",
            )
            t_post_llm_call = time.perf_counter()
            llm_called = draft is not None and bdv.requires_llm
            if draft is not None and bdv.speak == SpeakAction.RESPOND:
                text, policy_result = self._policy.apply_post_check(
                    draft,
                    pre.constraints,
                    voice,
                    self._adapter,
                    user_text=user_text,
                    bdv=bdv,
                )
            else:
                text = draft
            if text and voice.question_budget <= 0:
                text = strip_trailing_questions(text) or text
            cps_score, cps_hits = score_cps(text or "")

        t_end = time.perf_counter()
        if bdv.speak in (SpeakAction.SILENCE, SpeakAction.DEFER) or pre.input_blocked or not generate_text:
            timing = TurnTiming(
                pre_llm_ms=(t_end - t0) * 1000,
                llm_ms=None,
                post_llm_ms=0.0,
                total_ms=(t_end - t0) * 1000,
            )
        else:
            timing = TurnTiming(
                pre_llm_ms=(t_pre_llm - t0) * 1000,
                llm_ms=(t_post_llm_call - t_pre_llm) * 1000,
                post_llm_ms=(t_end - t_post_llm_call) * 1000,
                total_ms=(t_end - t0) * 1000,
            )

        if not commit_state:
            return (
                TurnOutput(
                    voice=voice,
                    text=text,
                    llm_called=llm_called,
                    cps_score=cps_score,
                    cps_hits=cps_hits,
                    bdv=bdv,
                    raw_bdv=raw_bdv,
                    effective_bdv=bdv,
                    anchor=updated_anchor,
                    policy_result=policy_result,
                    policy_input_blocked=pre.input_blocked,
                    policy_constraints=llm_constraints,
                    timing=timing,
                ),
                session,
            )

        reason_codes = reason_codes_from_bdv(bdv)
        next_arc = advance_arc(
            session.arc,
            speak=bdv.speak,
            effective_warmth=voice.effective_warmth,
            user_text=user_text,
            reason_codes=reason_codes,
        )
        next_history = update_turn_history(
            session.turn_history,
            speak=bdv.speak,
            assistant_text=text,
        )
        next_messages = append_messages(session.messages, user_text, text)

        next_session = session.model_copy(
            update={
                "arc": next_arc,
                "anchor": updated_anchor,
                "turn_history": next_history,
                "messages": next_messages,
                "turn_index": session.turn_index + 1,
                "updated_at": _utc_now(),
            }
        )

        return (
            TurnOutput(
                voice=voice,
                text=text,
                llm_called=llm_called,
                cps_score=cps_score,
                cps_hits=cps_hits,
                bdv=bdv,
                raw_bdv=raw_bdv,
                effective_bdv=bdv,
                anchor=updated_anchor,
                policy_result=policy_result,
                policy_input_blocked=pre.input_blocked,
                policy_constraints=llm_constraints,
                timing=timing,
            ),
            next_session,
        )


def _cap_question_budget(
    bdv: BehaviorDirectiveVector,
    profile: PersonalityProfile,
) -> BehaviorDirectiveVector:
    """Preset question_budget is a hard cap — companions with 0 never interview the user."""
    cap = max(0, profile.question_budget_cap)
    budget = min(bdv.question_budget, cap)
    if budget <= 0:
        return bdv.model_copy(update={"questions": QuestionPolicy.NONE, "question_budget": 0})
    return bdv.model_copy(update={"question_budget": budget})


def _apply_response_policy(
    bdv: BehaviorDirectiveVector,
    response_policy: str,
) -> BehaviorDirectiveVector:
    """Map raw engine decision to product-facing decision without losing raw BDV."""
    if response_policy == "live_voice":
        return _apply_live_voice_policy(bdv)
    if response_policy == "live_voice_natural":
        return _apply_natural_voice_policy(bdv)
    if response_policy != "always_answer":
        return bdv
    if bdv.speak not in (SpeakAction.SILENCE, SpeakAction.DEFER):
        return bdv

    return bdv.model_copy(
        update={
            "speak": SpeakAction.ACK_ONLY,
            "length": ResponseLength.MINIMAL,
            "questions": QuestionPolicy.NONE,
            "question_budget": 0,
            "partial_response": True,
            "engagement_level": max(0.35, bdv.engagement_level),
            "timing_delay_ms": 0,
        }
    )


def _apply_live_voice_policy(bdv: BehaviorDirectiveVector) -> BehaviorDirectiveVector:
    """Live voice must not dead-air on real user turns — Gemini ENGINE speaks."""
    if bdv.speak not in (SpeakAction.SILENCE, SpeakAction.DEFER):
        return bdv
    codes = set(bdv.reasoning.reason_codes if bdv.reasoning else [])
    if codes & {"continuation_request", "direct_question", "command", "instruction_request"}:
        return bdv.model_copy(
            update={
                "speak": SpeakAction.RESPOND,
                "length": ResponseLength.NORMAL,
                "questions": QuestionPolicy.NONE,
                "question_budget": 0,
                "partial_response": False,
                "engagement_level": 0.6,
                "timing_delay_ms": 0,
            }
        )
    if "social_greeting" in codes:
        return bdv.model_copy(
            update={
                "speak": SpeakAction.RESPOND,
                "length": ResponseLength.NORMAL,
                "questions": QuestionPolicy.NONE,
                "question_budget": 0,
                "engagement_level": 0.55,
                "timing_delay_ms": 0,
            }
        )
    if codes & {"closure_ack", "ack_or_backchannel"}:
        return bdv.model_copy(
            update={
                "speak": SpeakAction.ACK_ONLY,
                "length": ResponseLength.MINIMAL,
                "questions": QuestionPolicy.NONE,
                "question_budget": 0,
                "partial_response": True,
                "engagement_level": 0.35,
                "timing_delay_ms": 0,
            }
        )
    if bdv.speak == SpeakAction.DEFER:
        return bdv.model_copy(
            update={
                "speak": SpeakAction.RESPOND,
                "length": ResponseLength.NORMAL,
                "questions": QuestionPolicy.NONE,
                "question_budget": 0,
                "engagement_level": 0.55,
                "timing_delay_ms": 0,
            }
        )
    return bdv.model_copy(
        update={
            "speak": SpeakAction.ACK_ONLY,
            "length": ResponseLength.MINIMAL,
            "questions": QuestionPolicy.NONE,
            "question_budget": 0,
            "partial_response": True,
            "engagement_level": 0.35,
            "timing_delay_ms": 0,
        }
    )


def _apply_natural_voice_policy(bdv: BehaviorDirectiveVector) -> BehaviorDirectiveVector:
    """Natural S2S must answer — never SILENCE, DEFER, or canned ACK_ONLY."""
    if bdv.speak not in (SpeakAction.SILENCE, SpeakAction.DEFER, SpeakAction.ACK_ONLY):
        return bdv
    return bdv.model_copy(
        update={
            "speak": SpeakAction.RESPOND,
            "length": ResponseLength.NORMAL,
            "questions": QuestionPolicy.NONE,
            "question_budget": 0,
            "partial_response": False,
            "engagement_level": max(0.55, bdv.engagement_level),
            "timing_delay_ms": 0,
        }
    )


def _llm_constraints_ref(constraints) -> PolicyConstraintsRef:
    return PolicyConstraintsRef(
        inject_system_lines=list(constraints.inject_system_lines),
        blocked_phrases=list(constraints.blocked_phrases),
        required_disclaimer=constraints.required_disclaimer,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
