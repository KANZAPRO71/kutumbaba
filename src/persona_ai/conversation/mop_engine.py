"""MOP Engine — eligibility, state machine, steer metadata (not audio transport)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from persona_ai.conversation.experience_modes import MopPhase, normalize_experience_mode
from persona_ai.conversation.mop_telemetry import log_mop_event
from persona_ai.core.types import BehaviorDirectiveVector, BehaviorInput, SpeakAction
from persona_ai.behavior.interpret import interpret

MopFrequency = Literal["off", "very_low", "low", "adaptive_high"]
MopType = Literal[
    "observational",
    "wordplay",
    "callback_mop",
    "exaggeration",
    "misdirection",
    "teasing",
    "pantun",
    "local_reference",
]
MopReaction = Literal["laugh_short", "soft_laugh", "jedag", "none"]
MopOutcome = Literal["laughed", "responded", "ignored", "changed_topic"]

MAX_MOPS_PER_SESSION = 5
MIN_TURNS_BETWEEN_MOPS = 2
DEFAULT_HOLD_MS = 350


class MopFrequencyLevel(str, Enum):
    OFF = "off"
    VERY_LOW = "very_low"
    LOW = "low"
    ADAPTIVE_HIGH = "adaptive_high"


@dataclass
class MopEligibility:
    eligible: bool
    reason: str
    kind: MopType | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"eligible": self.eligible, "reason": self.reason, "kind": self.kind}


@dataclass
class MopTurnPlan:
    phase: MopPhase
    mop_type: MopType | None
    hold_ms: int = 0
    delivery_hint: str = "dry"
    steer_fragment: str | None = None
    reaction: MopReaction = "none"
    reaction_after_turn: bool = False
    timing_delay_ms: int = 0
    suppressed: bool = False
    suppress_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "mop_type": self.mop_type,
            "hold_ms": self.hold_ms,
            "delivery_hint": self.delivery_hint,
            "reaction": self.reaction,
            "reaction_after_turn": self.reaction_after_turn,
            "timing_delay_ms": self.timing_delay_ms,
            "suppressed": self.suppressed,
            "suppress_reason": self.suppress_reason,
        }


@dataclass
class MopSessionState:
    phase: MopPhase = MopPhase.IDLE
    mop_count_session: int = 0
    turns_since_last_mop: int = 0
    last_mop_at_turn: int = 0
    current_type: MopType | None = None
    hold_ms: int = DEFAULT_HOLD_MS
    recent_outcomes: list[str] = field(default_factory=list)
    session_turn: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "mop_count_session": self.mop_count_session,
            "turns_since_last_mop": self.turns_since_last_mop,
            "current_type": self.current_type,
            "hold_ms": self.hold_ms,
        }


_sessions: dict[str, MopSessionState] = {}


def reset_mop_sessions() -> None:
    _sessions.clear()


def get_mop_session(session_id: str) -> MopSessionState:
    if session_id not in _sessions:
        _sessions[session_id] = MopSessionState()
    return _sessions[session_id]


def mop_frequency_for_mode(mode: str | None) -> MopFrequency:
    mid = normalize_experience_mode(mode)
    table: dict[str, MopFrequency] = {
        "nongkrong": "low",
        "mop": "adaptive_high",
        "cerita_tong": "off",
        "teman_malam": "very_low",
        "teman_jalan": "off",
    }
    return table.get(mid, "low")


def _frequency_allows(frequency: MopFrequency, engagement: float) -> bool:
    if frequency == "off":
        return False
    if frequency == "very_low":
        return engagement >= 0.55
    if frequency == "low":
        return engagement >= 0.45
    return engagement >= 0.35


def evaluate_mop_eligibility(
    *,
    inp: BehaviorInput,
    bdv: BehaviorDirectiveVector,
    experience_mode: str | None,
    session: MopSessionState,
    callback_surfaced_this_turn: bool = False,
    user_turn_index: int = 0,
) -> MopEligibility:
    mode = normalize_experience_mode(experience_mode)
    frequency = mop_frequency_for_mode(mode)
    intent = interpret(inp.message, inp.history.last_assistant_word_count)
    engagement = bdv.engagement_level

    log_mop_event(
        "mop_candidate",
        {
            "experience_mode": mode,
            "frequency": frequency,
            "phase": session.phase.value,
            "engagement": engagement,
        },
    )

    if frequency == "off":
        return MopEligibility(eligible=False, reason="mode_mop_off")
    if session.phase == MopPhase.COOLDOWN and session.turns_since_last_mop < MIN_TURNS_BETWEEN_MOPS:
        return MopEligibility(eligible=False, reason="cooldown_active")
    if session.mop_count_session >= MAX_MOPS_PER_SESSION:
        return MopEligibility(eligible=False, reason="max_mops_per_session")
    if callback_surfaced_this_turn:
        return MopEligibility(eligible=False, reason="callback_surfaced")
    if intent.is_vent or intent.emotional_load >= 0.65:
        return MopEligibility(eligible=False, reason="user_serious")
    if mode == "cerita_tong" and intent.depth.value in {"moderate", "deep"}:
        return MopEligibility(eligible=False, reason="curhat_context")
    if bdv.speak not in (SpeakAction.RESPOND, SpeakAction.ACK_ONLY):
        return MopEligibility(eligible=False, reason=f"bdv_{bdv.speak.value.lower()}")
    if not _frequency_allows(frequency, engagement):
        return MopEligibility(eligible=False, reason="low_engagement")

    kind: MopType = "observational"
    if mode == "mop" and engagement >= 0.7:
        kind = "local_reference"
    elif inp.history.last_assistant_word_count < 12:
        kind = "teasing"

    log_mop_event(
        "mop_selected",
        {"experience_mode": mode, "kind": kind, "reason": "high_engagement"},
    )
    return MopEligibility(eligible=True, reason="high_engagement", kind=kind)


def _steer_for_phase(
    phase: MopPhase,
    *,
    mop_type: MopType | None,
    hold_ms: int,
    delivery_hint: str,
) -> str:
    kind = mop_type or "observational"
    if phase == MopPhase.SETUP:
        return (
            f"MOP SETUP ({kind}): bangun konteks — belum punchline. "
            "Satu atau dua kalimat pembuka natural, jangan joke dulu."
        )
    if phase == MopPhase.HOLD:
        return (
            f"MOP HOLD ({kind}): pause_ms={hold_ms} — tahan tension, "
            f"gaya {delivery_hint}. Jangan punchline di turn ini."
        )
    if phase == MopPhase.PUNCHLINE:
        return (
            f"MOP PUNCHLINE ({kind}): payoff sekarang — singkat, timing kering. "
            "Jangan setup panjang lagi."
        )
    return ""


def _next_phase(current: MopPhase) -> MopPhase:
    order = (
        MopPhase.IDLE,
        MopPhase.SETUP,
        MopPhase.HOLD,
        MopPhase.PUNCHLINE,
        MopPhase.REACTION,
        MopPhase.COOLDOWN,
        MopPhase.IDLE,
    )
    try:
        idx = order.index(current)
    except ValueError:
        return MopPhase.SETUP
    if current == MopPhase.IDLE:
        return MopPhase.SETUP
    if idx + 1 < len(order):
        return order[idx + 1]
    return MopPhase.IDLE


def plan_mop_turn(
    *,
    session_id: str,
    inp: BehaviorInput,
    bdv: BehaviorDirectiveVector,
    experience_mode: str | None,
    callback_surfaced_this_turn: bool = False,
    user_turn_index: int = 0,
) -> tuple[MopTurnPlan, MopSessionState]:
    state = get_mop_session(session_id)
    state.session_turn = user_turn_index
    state.turns_since_last_mop += 1

    eligibility = evaluate_mop_eligibility(
        inp=inp,
        bdv=bdv,
        experience_mode=experience_mode,
        session=state,
        callback_surfaced_this_turn=callback_surfaced_this_turn,
        user_turn_index=user_turn_index,
    )

    if not eligibility.eligible and state.phase in {MopPhase.IDLE, MopPhase.COOLDOWN}:
        log_mop_event(
            "mop_suppressed",
            {
                "experience_mode": normalize_experience_mode(experience_mode),
                "reason": eligibility.reason,
            },
        )
        return (
            MopTurnPlan(
                phase=state.phase,
                mop_type=state.current_type,
                suppressed=True,
                suppress_reason=eligibility.reason,
            ),
            state,
        )

    if state.phase in {MopPhase.IDLE, MopPhase.COOLDOWN}:
        if not eligibility.eligible:
            return (
                MopTurnPlan(
                    phase=state.phase,
                    mop_type=None,
                    suppressed=True,
                    suppress_reason=eligibility.reason,
                ),
                state,
            )
        state.phase = MopPhase.SETUP
        state.current_type = (
            "callback_mop" if callback_surfaced_this_turn else eligibility.kind
        )
        state.turns_since_last_mop = 0
    elif state.phase not in {MopPhase.REACTION, MopPhase.PUNCHLINE}:
        state.phase = _next_phase(state.phase)

    mop_type = state.current_type or eligibility.kind
    hold_ms = state.hold_ms or DEFAULT_HOLD_MS
    delivery = "dry" if mop_type != "pantun" else "playful"

    plan = MopTurnPlan(
        phase=state.phase,
        mop_type=mop_type,
        hold_ms=hold_ms if state.phase == MopPhase.HOLD else 0,
        delivery_hint=delivery,
    )

    if state.phase == MopPhase.HOLD:
        plan.timing_delay_ms = hold_ms
        log_mop_event(
            "mop_hold",
            {
                "hold_ms": hold_ms,
                "planned_hold_ms": hold_ms,
                "mop_type": mop_type,
            },
        )
    elif state.phase == MopPhase.SETUP:
        log_mop_event("mop_setup", {"mop_type": mop_type})
    elif state.phase == MopPhase.PUNCHLINE:
        log_mop_event("mop_punchline", {"mop_type": mop_type})
        plan.reaction = "laugh_short"
        plan.reaction_after_turn = True

    fragment = _steer_for_phase(
        state.phase, mop_type=mop_type, hold_ms=hold_ms, delivery_hint=delivery
    )
    if fragment:
        plan.steer_fragment = fragment

    return plan, state


def on_assistant_mop_complete(
    session_id: str,
    assistant_text: str,
    *,
    experience_mode: str | None,
) -> MopReaction:
    """After assistant turn — emit reaction cue metadata only."""
    state = get_mop_session(session_id)
    if state.phase != MopPhase.PUNCHLINE:
        return "none"

    text = (assistant_text or "").strip()
    if len(text) < 20:
        state.phase = MopPhase.COOLDOWN
        return "none"

    state.phase = MopPhase.REACTION
    state.mop_count_session += 1
    state.last_mop_at_turn = state.session_turn
    reaction: MopReaction = "laugh_short"
    profile_mode = normalize_experience_mode(experience_mode)
    if profile_mode == "mop":
        reaction = "laugh_short"
    elif profile_mode == "nongkrong":
        reaction = "soft_laugh"

    log_mop_event(
        "mop_reaction",
        {
            "mode": profile_mode,
            "mop_type": state.current_type,
            "reaction": reaction,
            "hold_ms": state.hold_ms,
        },
    )
    state.phase = MopPhase.COOLDOWN
    state.current_type = None
    return reaction


def record_mop_outcome(session_id: str, user_text: str) -> MopOutcome | None:
    state = get_mop_session(session_id)
    if state.phase != MopPhase.COOLDOWN and state.mop_count_session == 0:
        return None
    text = " ".join((user_text or "").split()).lower()
    if any(x in text for x in ("😂", "haha", "wkwk", "ngakak")):
        outcome: MopOutcome = "laughed"
    elif any(x in text for x in ("cerita lain", "ganti topik", "skip")):
        outcome = "changed_topic"
    elif len(text.split()) >= 8:
        outcome = "responded"
    elif len(text.split()) <= 3:
        outcome = "ignored"
    else:
        outcome = "responded"
    state.recent_outcomes.append(outcome)
    state.recent_outcomes = state.recent_outcomes[-8:]
    log_mop_event(
        "mop_outcome",
        {
            "outcome": outcome,
            "mop_count": state.mop_count_session,
            "mop_type": state.current_type,
            "planned_hold_ms": state.hold_ms,
            "hold_ms": state.hold_ms,
        },
    )
    if state.phase == MopPhase.COOLDOWN:
        state.phase = MopPhase.IDLE
    return outcome
