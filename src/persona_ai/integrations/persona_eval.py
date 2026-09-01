"""Persona eval client — thin PersonaRuntime integration for A/B experiments."""

from __future__ import annotations

from persona_ai.llm.adapter import LLMAdapter, default_adapter
from persona_ai.personality.preset import load_preset_by_id
from persona_ai.runtime import PersonaRuntime, TurnOutput
from persona_ai.session.store import InMemorySessionStore, SessionStore


class PersonaEvalClient:
    """Treatment arm — Persona governance before Gemini."""

    def __init__(
        self,
        preset_id: str = "default_companion",
        llm_adapter: LLMAdapter | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self._preset_id = preset_id
        profile = load_preset_by_id(preset_id)
        self._runtime = PersonaRuntime(
            session_store=session_store or InMemorySessionStore(),
            personality_profile=profile,
            llm_adapter=llm_adapter or default_adapter(),
        )

    @property
    def runtime(self) -> PersonaRuntime:
        return self._runtime

    @property
    def preset_id(self) -> str:
        return self._preset_id

    def process_turn(self, session_id: str, user_text: str, **kwargs: object) -> TurnOutput:
        return self._runtime.process_turn(session_id, user_text, **kwargs)
