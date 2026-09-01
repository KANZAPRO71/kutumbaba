"""Retell custom-LLM webhook POC — Persona governance before agent speech.

Wire this handler into Retell's custom LLM / agent-response hook after STT
finalizes a user utterance.

This module does NOT start an HTTP server — integrate with FastAPI/Flask in your
deployment layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from persona_ai.core.types import SpeakAction
from persona_ai.llm.adapter import LLMAdapter, default_adapter
from persona_ai.personality.preset import load_preset_by_id
from persona_ai.runtime import PersonaRuntime, TurnOutput


class RetellResponseType(str, Enum):
    """How Retell (or any voice transport) should act on this turn."""

    NO_RESPONSE = "no_response"
    SPEAK = "speak"


@dataclass
class RetellWebhookRequest:
    """Normalized payload from a voice turn (post-STT)."""

    session_id: str
    transcript: str
    voice_pause_ms: int | None = None
    call_id: str | None = None


@dataclass
class RetellWebhookResponse:
    """Response for TTS layer / Retell agent reply."""

    response_type: RetellResponseType
    text: str | None = None
    delay_ms: int = 0
    bdv_action: str | None = None
    llm_called: bool = False
    trace: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "response_type": self.response_type.value,
            "text": self.text,
            "delay_ms": self.delay_ms,
            "bdv_action": self.bdv_action,
            "llm_called": self.llm_called,
            "trace": self.trace,
        }


class RetellPersonaBridge:
    """Stateful bridge — one PersonaRuntime per deployment, sessions keyed by call."""

    def __init__(
        self,
        *,
        preset_id: str = "default_companion",
        llm_adapter: LLMAdapter | None = None,
        runtime: PersonaRuntime | None = None,
    ) -> None:
        if runtime is not None:
            self._runtime = runtime
        else:
            profile = load_preset_by_id(preset_id)
            self._runtime = PersonaRuntime(
                personality_profile=profile,
                llm_adapter=llm_adapter or default_adapter(),
            )

    @property
    def runtime(self) -> PersonaRuntime:
        return self._runtime

    def handle_turn(self, request: RetellWebhookRequest) -> RetellWebhookResponse:
        """Run Persona governance for one finalized transcript."""
        output = self._runtime.process_turn(
            request.session_id,
            request.transcript,
            voice_pause_ms=request.voice_pause_ms,
        )
        return turn_output_to_retell(output, call_id=request.call_id)

    def handle_dict(self, payload: dict[str, Any]) -> dict[str, Any]:
        """JSON-friendly entry for HTTP handlers."""
        req = RetellWebhookRequest(
            session_id=str(payload.get("session_id") or payload.get("call_id") or "default"),
            transcript=str(payload.get("transcript") or payload.get("user_message") or ""),
            voice_pause_ms=payload.get("voice_pause_ms"),
            call_id=payload.get("call_id"),
        )
        return self.handle_turn(req).to_dict()


def turn_output_to_retell(
    output: TurnOutput,
    *,
    call_id: str | None = None,
) -> RetellWebhookResponse:
    """Map Persona TurnOutput → voice transport response."""
    bdv = output.bdv
    action = bdv.speak.value if bdv else SpeakAction.RESPOND.value
    delay_ms = bdv.timing_delay_ms if bdv else 0

    trace: dict[str, Any] | None = None
    if output.trace is not None:
        trace = {
            "session_id": output.trace.session_id,
            "turn_index": output.trace.turn_index,
            "bdv_action": output.trace.bdv_action,
            "execution_profile": output.trace.execution_profile,
            "llm_called": output.trace.llm_called,
            "call_id": call_id,
        }
        if output.trace.timing is not None:
            trace["pre_llm_ms"] = output.trace.timing.pre_llm_ms

    if action in (SpeakAction.SILENCE.value, SpeakAction.DEFER.value):
        return RetellWebhookResponse(
            response_type=RetellResponseType.NO_RESPONSE,
            text=None,
            delay_ms=delay_ms,
            bdv_action=action,
            llm_called=output.llm_called,
            trace=trace,
        )

    return RetellWebhookResponse(
        response_type=RetellResponseType.SPEAK,
        text=output.text,
        delay_ms=delay_ms,
        bdv_action=action,
        llm_called=output.llm_called,
        trace=trace,
    )
