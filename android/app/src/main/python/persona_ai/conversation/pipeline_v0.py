"""v0 pipeline — thin compatibility wrapper around PersonaRuntime."""

from __future__ import annotations

from persona_ai.coherence.bind import IdentityAnchor
from persona_ai.core.types import Message, PersonalityProfile, TurnHistory
from persona_ai.llm.adapter import LLMAdapter
from persona_ai.runtime import PersonaRuntime, TurnOutput, TurnOverrides

_compat_runtime: PersonaRuntime | None = None


def _get_compat_runtime(
    profile: PersonalityProfile | None = None,
    adapter: LLMAdapter | None = None,
) -> PersonaRuntime:
    global _compat_runtime
    if profile is not None or adapter is not None:
        return PersonaRuntime(
            session_store=_compat_store(),
            personality_profile=profile,
            llm_adapter=adapter,
        )
    if _compat_runtime is None:
        _compat_runtime = PersonaRuntime(session_store=_compat_store())
    return _compat_runtime


def _compat_store():
    from persona_ai.session.store import InMemorySessionStore

    if not hasattr(_compat_store, "_store"):
        _compat_store._store = InMemorySessionStore()  # type: ignore[attr-defined]
    return _compat_store._store  # type: ignore[attr-defined]


def process_turn(
    session_id: str,
    user_text: str,
    history: TurnHistory | None = None,
    anchor: IdentityAnchor | None = None,
    profile: PersonalityProfile | None = None,
    adapter: LLMAdapter | None = None,
    message_history: list[Message] | None = None,
    voice_pause_ms: int | None = None,
) -> TurnOutput:
    """Compatibility entry — prefer PersonaRuntime for new integrations."""
    has_overrides = history is not None or anchor is not None or message_history is not None
    runtime = _get_compat_runtime(profile=profile, adapter=adapter)

    if has_overrides:
        return runtime.process_turn(
            session_id,
            user_text,
            overrides=TurnOverrides(
                history=history,
                anchor=anchor,
                messages=message_history,
            ),
            persist=False,
            voice_pause_ms=voice_pause_ms,
        )

    return runtime.process_turn(
        session_id,
        user_text,
        persist=True,
        voice_pause_ms=voice_pause_ms,
    )


__all__ = ["TurnOutput", "process_turn"]
