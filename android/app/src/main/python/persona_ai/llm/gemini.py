"""Gemini Interactions API adapter — renderer only."""

from __future__ import annotations

import os
import re
import time
from typing import Any, Protocol

from persona_ai.core.types import (
    LLMRequest,
    LLMResponse,
    Message,
    PolicyConstraintsRef,
    VoiceDirective,
)
from persona_ai.env import load_project_dotenv
from persona_ai.llm.gemini_models import DEFAULT_GEMINI_TEXT_MODEL, gemini_text_model
from persona_ai.llm.interactions_history import build_interactions_input
from persona_ai.llm.prompt import build_system_prompt

DEFAULT_GEMINI_MODEL = DEFAULT_GEMINI_TEXT_MODEL


load_project_dotenv()

class GeminiAdapterError(RuntimeError):
    """Base error for Gemini adapter failures."""


class GeminiCredentialsError(GeminiAdapterError):
    """Raised when Gemini adapter is requested without credentials."""


class GeminiEmptyOutputError(GeminiAdapterError):
    """Raised when Interactions API returns no usable text."""


class GeminiInteractionClient(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class GeminiLLMAdapter:
    """Thin Gemini renderer via google-genai Interactions API (store=False)."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model or gemini_text_model()
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise GeminiCredentialsError(
                "GEMINI_API_KEY not set. Install persona-ai[gemini] and configure credentials."
            )
        try:
            from google import genai
        except ImportError as exc:
            raise GeminiAdapterError(
                "google-genai is required. Install with: pip install persona-ai[gemini]"
            ) from exc
        self._client = genai.Client(api_key=self.api_key)
        return self._client

    def render(
        self,
        voice_directive: VoiceDirective,
        user_text: str,
        history: list[Message] | None = None,
        policy_constraints: PolicyConstraintsRef | None = None,
    ) -> str:
        req = LLMRequest(
            user_message=user_text,
            voice=voice_directive,
            history=history or [],
            policy_constraints=policy_constraints,
        )
        return self.complete(req).text

    def complete(self, request: LLMRequest) -> LLMResponse:
        system_instruction = build_system_prompt(request)
        interaction_input = build_interactions_input(
            request.history,
            request.user_message,
        )
        max_retries = 6
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                interaction = self.client.interactions.create(
                    model=self.model,
                    input=interaction_input,
                    store=False,
                    system_instruction=system_instruction,
                )
                break
            except GeminiAdapterError:
                raise
            except Exception as exc:
                last_exc = exc
                if _is_rate_limited(exc) and attempt < max_retries - 1:
                    time.sleep(_retry_after_seconds(exc))
                    continue
                raise GeminiAdapterError(f"Gemini Interactions call failed: {exc}") from exc
        else:
            raise GeminiAdapterError(f"Gemini Interactions call failed: {last_exc}") from last_exc

        text = _extract_output_text(interaction)
        if not text:
            raise GeminiEmptyOutputError("Gemini Interactions returned empty output_text")

        usage = getattr(getattr(interaction, "usage", None), "total_tokens", 0) or 0
        return LLMResponse(text=text.strip(), model=self.model, usage_tokens=usage)


def _extract_output_text(interaction: Any) -> str:
    output_text = getattr(interaction, "output_text", None)
    if output_text:
        return str(output_text).strip()
    steps = getattr(interaction, "steps", None) or []
    for step in reversed(steps):
        step_type = getattr(step, "type", None) or (step.get("type") if isinstance(step, dict) else None)
        if step_type != "model_output":
            continue
        content = getattr(step, "content", None) or (step.get("content") if isinstance(step, dict) else None)
        if not content:
            continue
        parts: list[str] = []
        for block in content:
            block_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
            if block_type == "text":
                text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
                if text:
                    parts.append(str(text))
        if parts:
            return " ".join(parts).strip()
    return ""


def _is_rate_limited(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in ("429", "quota", "rate limit", "too_many_requests"))


def _retry_after_seconds(exc: Exception) -> float:
    match = re.search(r"retry in ([\d.]+)s", str(exc), re.IGNORECASE)
    if match:
        return float(match.group(1)) + 1.0
    return 15.0
