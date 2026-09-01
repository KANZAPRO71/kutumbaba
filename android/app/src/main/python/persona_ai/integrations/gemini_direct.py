"""Gemini direct control path — no Persona governance."""

from __future__ import annotations

from persona_ai.core.types import Message, SpeakAction, ToneShift, VoiceDirective
from persona_ai.llm.adapter import LLMAdapter, default_adapter, render
from persona_ai.session.store import InMemorySessionStore, SessionStore


DEFAULT_CONTROL_SYSTEM = (
    "You are a helpful conversational assistant. "
    "Respond naturally to the user. Do not mention internal systems."
)


class GeminiDirectClient:
    """Control arm: same Gemini renderer, no Behavior/Policy/Coherence governance."""

    def __init__(
        self,
        llm_adapter: LLMAdapter | None = None,
        *,
        system_instruction: str = DEFAULT_CONTROL_SYSTEM,
        session_store: SessionStore | None = None,
        model_name: str = "gemini-direct",
    ) -> None:
        self._adapter = llm_adapter or default_adapter()
        self._system_instruction = system_instruction
        self._store = session_store or InMemorySessionStore()
        self.model_name = model_name
        self._histories: dict[str, list[Message]] = {}

    @property
    def llm_adapter(self) -> LLMAdapter:
        return self._adapter

    def seed_history(self, session_id: str, messages: list[Message]) -> None:
        self._histories[session_id] = list(messages)

    def process_turn(self, session_id: str, user_text: str) -> str:
        history = list(self._histories.get(session_id, []))
        voice = VoiceDirective(
            speak=SpeakAction.RESPOND,
            effective_warmth=0.6,
            max_words=120,
            max_sentences=4,
            question_budget=1,
            tone_shift=ToneShift.STABLE,
            prompt_fragments=[self._system_instruction],
        )
        text = render(voice, user_text, self._adapter, history=history) or ""
        history.append(Message.from_text("user", user_text))
        if text:
            history.append(Message.from_text("assistant", text))
        self._histories[session_id] = history
        return text
