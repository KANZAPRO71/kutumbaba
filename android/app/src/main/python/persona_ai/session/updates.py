"""Post-turn session state updates — arc + history advancement."""

from __future__ import annotations

from persona_ai.core.types import (
    ArcPhase,
    BehaviorDirectiveVector,
    ConversationArc,
    Message,
    ResponseLength,
    SpeakAction,
    TurnHistory,
    clamp,
)


def _verbosity_from_words(count: int) -> ResponseLength:
    if count >= 40:
        return ResponseLength.EXPAND
    if count <= 8:
        return ResponseLength.MINIMAL
    return ResponseLength.NORMAL


def _assistant_words(text: str | None, speak: SpeakAction) -> int:
    if not text:
        return 55 if speak == SpeakAction.SILENCE else 0
    return len(text.split())


def advance_arc(
    arc: ConversationArc,
    *,
    speak: SpeakAction,
    effective_warmth: float,
    user_text: str,
    reason_codes: list[str],
) -> ConversationArc:
    turn_count = arc.turn_count + 1
    emotional = speak in (SpeakAction.ACK_ONLY, SpeakAction.RESPOND) and any(
        c in reason_codes for c in ("user_venting", "mixed_intent", "confusion_signal")
    )
    warmth_delta = 0.015 if emotional else -0.004
    relational_warmth = clamp(arc.relational_warmth + warmth_delta, 0.25, 0.82)

    phase = arc.arc_phase
    if turn_count >= 14:
        phase = ArcPhase.WINDING_DOWN
    elif turn_count >= 8:
        phase = ArcPhase.DEEPENING
    elif turn_count >= 3:
        phase = ArcPhase.EXPLORATION

    warmth_series_hint = abs(effective_warmth - relational_warmth)
    emotional_drift = clamp(0.85 * arc.emotional_drift + 0.15 * warmth_series_hint)

    closure_attempts = arc.closure_attempts
    if user_text.strip().lower() in {"oke", "ok", "thanks", "sip", "noted", "bye"}:
        closure_attempts += 1

    return arc.model_copy(
        update={
            "turn_count": turn_count,
            "relational_warmth": relational_warmth,
            "emotional_drift": emotional_drift,
            "arc_phase": phase,
            "closure_attempts": closure_attempts,
        }
    )


def update_turn_history(
    history: TurnHistory,
    *,
    speak: SpeakAction,
    assistant_text: str | None,
) -> TurnHistory:
    assistant_words = _assistant_words(assistant_text, speak)
    if speak in (SpeakAction.SILENCE, SpeakAction.DEFER):
        return TurnHistory(
            last_speaker="user",
            last_assistant_word_count=history.last_assistant_word_count,
            last_assistant_verbosity=history.last_assistant_verbosity,
            consecutive_assistant_turns=0,
        )
    if assistant_words > 0 or assistant_text:
        return TurnHistory(
            last_speaker="assistant",
            last_assistant_word_count=assistant_words or history.last_assistant_word_count,
            last_assistant_verbosity=_verbosity_from_words(assistant_words or 20),
            consecutive_assistant_turns=history.consecutive_assistant_turns + 1,
        )
    return TurnHistory(last_speaker="user")


def append_messages(
    messages: list[Message],
    user_text: str,
    assistant_text: str | None,
) -> list[Message]:
    updated = list(messages)
    updated.append(Message.from_text("user", user_text))
    if assistant_text:
        updated.append(Message.from_text("assistant", assistant_text))
    return updated


def reason_codes_from_bdv(bdv: BehaviorDirectiveVector | None) -> list[str]:
    if bdv is None or bdv.reasoning is None:
        return []
    return list(bdv.reasoning.reason_codes)
