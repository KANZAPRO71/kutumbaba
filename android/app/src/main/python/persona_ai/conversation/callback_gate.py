"""Callback Gate — eligibility & selection; never speaks directly."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal

from persona_ai.conversation.callback_daily_store import get_callback_daily_store
from persona_ai.conversation.callback_telemetry import log_callback_event
from persona_ai.conversation.experience_modes import get_experience_profile, normalize_experience_mode
from persona_ai.conversation.proactive_followup import (
    CallbackCandidate,
    callback_expression_hint,
    callback_internal_steer,
)
from persona_ai.core.types import SpeakAction
from persona_ai.memory.models import DEFAULT_USER_ID
from persona_ai.memory.open_loop_engine import (
    list_pending_open_loops,
    mark_loop_callback_surfaced,
    mark_loop_mentioned,
    record_loop_callback_outcome,
)
from persona_ai.memory.open_loop_models import OpenLoopRecord

CallbackOutcome = Literal["engaged", "neutral", "ignored", "redirected"]

LOOP_CALLBACK_COOLDOWN_DAYS = 2
MIN_PRIORITY = 0.35


@dataclass
class CallbackGateChecks:
    priority_ok: bool = False
    mode_allows_callback: bool = False
    not_mentioned_today: bool = False
    not_already_callback_today: bool = False
    not_recently_repeated: bool = False
    user_context_allows: bool = False
    session_ready: bool = False


@dataclass
class CallbackGateDecision:
    eligible: bool
    reason: str
    loop_id: str | None = None
    priority: float = 0.0
    checks: CallbackGateChecks = field(default_factory=CallbackGateChecks)
    checks_map: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "loop_id": self.loop_id,
            "priority": self.priority,
            "checks": self.checks_map or {
                "priority_ok": self.checks.priority_ok,
                "mode_allows_callback": self.checks.mode_allows_callback,
                "not_mentioned_today": self.checks.not_mentioned_today,
                "not_already_callback_today": self.checks.not_already_callback_today,
                "not_recently_repeated": self.checks.not_recently_repeated,
                "user_context_allows": self.checks.user_context_allows,
                "session_ready": self.checks.session_ready,
            },
        }


@dataclass
class CallbackTurnResult:
    candidate_count: int = 0
    selected: CallbackCandidate | None = None
    decision: CallbackGateDecision | None = None
    surfaced: bool = False
    steer_fragment: str | None = None
    expression_hint: str | None = None
    suppressed_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "selected_loop_id": self.selected.loop_id if self.selected else None,
            "surfaced": self.surfaced,
            "decision": self.decision.to_dict() if self.decision else None,
            "suppressed_reason": self.suppressed_reason,
        }


def _utc_today() -> str:
    return date.today().isoformat()


def _parse_day(iso: str | None) -> date | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(iso[:10])
        except ValueError:
            return None


def loop_priority(loop: OpenLoopRecord) -> float:
    base = float(loop.confidence or 0.5)
    content = (loop.content or "").strip()
    if len(content) >= 40:
        base += 0.08
    if loop.time_hint:
        base += 0.05
    return min(1.0, base)


def _loop_mentioned_today(loop: OpenLoopRecord) -> bool:
    day = _parse_day(loop.last_mentioned_at)
    return day == date.today()


def _loop_callback_cooldown_active(loop: OpenLoopRecord) -> bool:
    day = _parse_day(loop.last_callback_at)
    if day is None:
        return False
    return (date.today() - day).days < LOOP_CALLBACK_COOLDOWN_DAYS


def _user_context_allows(user_text: str, *, selective: bool, session_user_turns: int) -> bool:
    text = " ".join((user_text or "").split()).strip()
    if len(text) < 8:
        return False
    _ = session_user_turns
    if not selective:
        return True
    words = text.lower().split()
    if len(words) >= 5:
        return True
    soft = {"santai", "curhat", "cerita", "ngobrol", "boring", "bosan", "tenang", "lagi"}
    return any(w in soft for w in words)


def evaluate_loop_callback(
    loop: OpenLoopRecord,
    *,
    experience_mode: str | None,
    user_text: str,
    session_user_turns: int,
    callbacks_surfaced_today: int,
) -> CallbackGateDecision:
    mode = normalize_experience_mode(experience_mode)
    profile = get_experience_profile(mode)
    priority = loop_priority(loop)
    selective = bool(profile and profile.callback.selective)
    policy_enabled = profile.callback.enabled if profile else True
    max_per_day = profile.callback.max_per_day if profile else 1

    checks = CallbackGateChecks()
    checks.priority_ok = priority >= MIN_PRIORITY
    checks.mode_allows_callback = policy_enabled
    checks.not_mentioned_today = not _loop_mentioned_today(loop)
    checks.not_already_callback_today = callbacks_surfaced_today < max(1, max_per_day)
    checks.not_recently_repeated = not _loop_callback_cooldown_active(loop)
    checks.session_ready = bool(user_text.strip())
    checks.user_context_allows = _user_context_allows(
        user_text, selective=selective, session_user_turns=session_user_turns
    )

    checks_map = {
        "priority_ok": checks.priority_ok,
        "mode_allows_callback": checks.mode_allows_callback,
        "not_mentioned_today": checks.not_mentioned_today,
        "not_already_callback_today": checks.not_already_callback_today,
        "not_recently_repeated": checks.not_recently_repeated,
        "user_context_allows": checks.user_context_allows,
        "session_ready": checks.session_ready,
    }

    if not checks.mode_allows_callback:
        return CallbackGateDecision(
            eligible=False,
            reason="mode_disallows_callback",
            loop_id=loop.id,
            priority=priority,
            checks=checks,
            checks_map=checks_map,
        )
    if not checks.session_ready:
        return CallbackGateDecision(
            eligible=False,
            reason="session_not_ready",
            loop_id=loop.id,
            priority=priority,
            checks=checks,
            checks_map=checks_map,
        )
    if not checks.priority_ok:
        return CallbackGateDecision(
            eligible=False,
            reason="priority_below_threshold",
            loop_id=loop.id,
            priority=priority,
            checks=checks,
            checks_map=checks_map,
        )
    if not checks.not_mentioned_today:
        return CallbackGateDecision(
            eligible=False,
            reason="mentioned_today",
            loop_id=loop.id,
            priority=priority,
            checks=checks,
            checks_map=checks_map,
        )
    if not checks.not_already_callback_today:
        return CallbackGateDecision(
            eligible=False,
            reason="callback_used_today",
            loop_id=loop.id,
            priority=priority,
            checks=checks,
            checks_map=checks_map,
        )
    if not checks.not_recently_repeated:
        return CallbackGateDecision(
            eligible=False,
            reason="loop_cooldown",
            loop_id=loop.id,
            priority=priority,
            checks=checks,
            checks_map=checks_map,
        )
    if not checks.user_context_allows:
        return CallbackGateDecision(
            eligible=False,
            reason="user_context_not_ready",
            loop_id=loop.id,
            priority=priority,
            checks=checks,
            checks_map=checks_map,
        )

    reason = "high_priority_unresolved" if priority >= 0.7 else "eligible_unresolved"
    return CallbackGateDecision(
        eligible=True,
        reason=reason,
        loop_id=loop.id,
        priority=priority,
        checks=checks,
        checks_map=checks_map,
    )


def select_callback_candidate(
    *,
    experience_mode: str | None,
    user_text: str,
    session_user_turns: int,
    user_id: str = DEFAULT_USER_ID,
) -> CallbackTurnResult:
    store = get_callback_daily_store()
    surfaced_today = store.surfaced_today()
    pending = list_pending_open_loops(user_id, limit=12)
    result = CallbackTurnResult()

    eligible: list[tuple[OpenLoopRecord, CallbackGateDecision]] = []
    for loop in pending:
        decision = evaluate_loop_callback(
            loop,
            experience_mode=experience_mode,
            user_text=user_text,
            session_user_turns=session_user_turns,
            callbacks_surfaced_today=surfaced_today,
        )
        log_callback_event(
            "callback_candidate",
            {
                "experience_mode": normalize_experience_mode(experience_mode),
                "loop_id": loop.id,
                "priority": decision.priority,
                "decision": "eligible" if decision.eligible else "suppressed",
                "reason": decision.reason,
            },
        )
        if decision.eligible:
            eligible.append((loop, decision))

    result.candidate_count = len(eligible)
    if eligible:
        store.increment_candidates(len(eligible))

    if not eligible:
        result.decision = CallbackGateDecision(eligible=False, reason="no_eligible_loops")
        return result

    loop, decision = max(eligible, key=lambda pair: loop_priority(pair[0]))
    result.decision = decision
    result.selected = CallbackCandidate(
        loop_id=loop.id,
        topic=loop.topic,
        content=loop.content,
        time_hint=loop.time_hint,
        priority=decision.priority,
        tone="natural",
    )
    store.increment_selected()
    log_callback_event(
        "callback_selected",
        {
            "experience_mode": normalize_experience_mode(experience_mode),
            "loop_id": loop.id,
            "priority": decision.priority,
            "reason": decision.reason,
        },
    )
    return result


def surface_callback_if_allowed(
    turn: CallbackTurnResult,
    *,
    experience_mode: str | None,
    bdv_speak: SpeakAction,
    language: str = "id",
    session_id: str | None = None,
) -> CallbackTurnResult:
    if turn.selected is None or turn.decision is None or not turn.decision.eligible:
        return turn

    if bdv_speak not in (SpeakAction.RESPOND, SpeakAction.ACK_ONLY):
        turn.suppressed_reason = f"bdv_{bdv_speak.value.lower()}"
        log_callback_event(
            "callback_suppressed",
            {
                "experience_mode": normalize_experience_mode(experience_mode),
                "loop_id": turn.selected.loop_id,
                "reason": turn.suppressed_reason,
                "session_id": session_id,
            },
        )
        return turn

    mode = normalize_experience_mode(experience_mode)
    turn.expression_hint = callback_expression_hint(turn.selected, experience_mode=mode, language=language)
    turn.steer_fragment = callback_internal_steer(turn.selected, experience_mode=mode, language=language)
    turn.surfaced = True

    mark_loop_callback_surfaced(turn.selected.loop_id)
    get_callback_daily_store().record_surfaced(turn.selected.loop_id)
    log_callback_event(
        "callback_surfaced",
        {
            "experience_mode": mode,
            "loop_id": turn.selected.loop_id,
            "priority": turn.selected.priority,
            "session_id": session_id,
        },
    )
    return turn


def evaluate_callback_turn(
    *,
    user_text: str,
    experience_mode: str | None,
    session_user_turns: int,
    bdv_speak: SpeakAction,
    language: str = "id",
    session_id: str | None = None,
) -> CallbackTurnResult:
    """Full gate for one user turn — selection + behavior-gated surface."""
    daily = get_callback_daily_store().load()
    if daily.pending_outcome_loop_id:
        from persona_ai.memory.open_loop_engine import get_open_loop_store

        loop = get_open_loop_store().get(daily.pending_outcome_loop_id)
        snippet = loop.content if loop else None
        outcome = resolve_pending_callback_outcome(
            user_text,
            pending_loop_id=daily.pending_outcome_loop_id,
            pending_snippet=snippet,
        )
        if outcome:
            get_callback_daily_store().clear_pending_outcome()
            log_callback_event(
                "callback_outcome",
                {
                    "loop_id": daily.pending_outcome_loop_id,
                    "callback_outcome": outcome,
                },
            )

    note_user_mentioned_loops(user_text)

    turn = select_callback_candidate(
        experience_mode=experience_mode,
        user_text=user_text,
        session_user_turns=session_user_turns,
    )
    return surface_callback_if_allowed(
        turn,
        experience_mode=experience_mode,
        bdv_speak=bdv_speak,
        language=language,
        session_id=session_id,
    )


def resolve_pending_callback_outcome(
    user_text: str,
    *,
    pending_loop_id: str | None,
    pending_snippet: str | None,
) -> CallbackOutcome | None:
    if not pending_loop_id:
        return None
    text = " ".join((user_text or "").split()).strip().lower()
    if not text:
        return None
    snippet = " ".join((pending_snippet or "").split()).lower()
    snippet_tokens = set(snippet.split()) if snippet else set()

    redirect_markers = (
        "cerita lain",
        "topik lain",
        "ganti topik",
        "skip",
        "lain dulu",
        "eh sekarang",
    )
    if any(m in text for m in redirect_markers):
        outcome: CallbackOutcome = "redirected"
    elif len(text.split()) >= 18:
        outcome = "engaged"
    elif snippet_tokens and len(set(text.split()) & snippet_tokens) >= 2:
        outcome = "engaged"
    elif len(text.split()) <= 4:
        outcome = "ignored"
    else:
        outcome = "neutral"

    record_loop_callback_outcome(pending_loop_id, outcome)
    log_callback_event(
        "callback_followed_up",
        {"loop_id": pending_loop_id, "callback_outcome": outcome},
    )
    return outcome


def note_user_mentioned_loops(user_text: str, *, user_id: str = DEFAULT_USER_ID) -> None:
    text = " ".join((user_text or "").split()).strip().lower()
    if len(text) < 6:
        return
    for loop in list_pending_open_loops(user_id, limit=20):
        snippet = " ".join((loop.content or "").split()).lower()
        if not snippet:
            continue
        tokens = [t for t in snippet.split() if len(t) >= 4][:6]
        if tokens and sum(1 for t in tokens if t in text) >= 2:
            mark_loop_mentioned(loop.id)


def should_callback(
    *,
    mode: str | None,
    loop_priority: float,
    mentioned_today: bool,
    callbacks_used_today: int,
    min_priority: float = MIN_PRIORITY,
) -> bool:
    """Legacy boolean API — prefer evaluate_loop_callback."""
    profile = get_experience_profile(mode)
    if profile is not None and not profile.callback.enabled:
        return False
    if loop_priority < min_priority:
        return False
    if mentioned_today:
        return False
    max_per_day = profile.callback.max_per_day if profile else 1
    if callbacks_used_today >= max_per_day:
        return False
    return True
