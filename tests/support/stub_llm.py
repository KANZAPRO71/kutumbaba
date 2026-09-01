"""Deterministic LLM stub — tests only, not shipped as production fallback."""

from __future__ import annotations

from persona_ai.core.types import LLMRequest, LLMResponse, SpeakAction


class StubLLMAdapter:
    model = "stub"

    def complete(self, request: LLMRequest) -> LLMResponse:
        v = request.voice
        if v.speak == SpeakAction.ACK_ONLY:
            return LLMResponse(text="Istirahat dulu, capek juga dengerinnya.", model=self.model)
        if v.speak == SpeakAction.RESPOND:
            text = (
                "Oke, besok meeting jam 9."
                if "meeting" in request.user_message.lower()
                else "Singkat saja."
            )
            words = text.split()[: v.max_words]
            return LLMResponse(text=" ".join(words), model=self.model)
        return LLMResponse(text="", model=self.model)
