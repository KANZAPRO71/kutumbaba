"""Thin LLM adapters — v0.4."""

from __future__ import annotations

import os
import re
from typing import Protocol

from persona_ai.core.types import LLMRequest, LLMResponse, PolicyConstraintsRef, SpeakAction, VoiceDirective
from persona_ai.llm.gemini import GeminiLLMAdapter
from persona_ai.llm.prompt import build_chat_messages


class LLMAdapter(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...


def default_adapter() -> LLMAdapter:
    """Production default — Gemini (GEMINI_API_KEY required on complete)."""
    return GeminiLLMAdapter()


class OpenAILLMAdapter:
    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    def complete(self, request: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("Install openai: pip install persona-ai[openai]") from e

        client = OpenAI(api_key=self.api_key)
        messages = build_chat_messages(request)
        resp = client.chat.completions.create(model=self.model, messages=messages, max_tokens=120)
        text = resp.choices[0].message.content or ""
        usage = resp.usage.total_tokens if resp.usage else 0
        return LLMResponse(text=text.strip(), model=self.model, usage_tokens=usage)


def get_adapter(name: str = "gemini") -> LLMAdapter:
    if name == "openai":
        return OpenAILLMAdapter()
    if name == "gemini":
        return GeminiLLMAdapter()
    raise ValueError(f"Unknown adapter {name!r}; use 'gemini' or 'openai'.")


def render(
    voice: VoiceDirective,
    user_message: str,
    adapter: LLMAdapter | None = None,
    history: list | None = None,
    policy_constraints: PolicyConstraintsRef | None = None,
    *,
    agent_timezone: str | None = None,
    language: str = "id",
) -> str | None:
    """Render text from BDV + VoiceDirective. No behavior re-decide."""
    if voice.speak in (SpeakAction.SILENCE, SpeakAction.DEFER):
        return None

    adapter = adapter or default_adapter()
    req = LLMRequest(
        user_message=user_message,
        voice=voice,
        history=history or [],
        policy_constraints=policy_constraints,
        agent_timezone=agent_timezone,
        language=language,
    )
    return adapter.complete(req).text


# --- CPS async logging (regex v0) ---

CHATBOT_PATTERNS = [
    (re.compile(r"ada lagi yang (bisa|mau)", re.I), "CP1"),
    (re.compile(r"ada (lagi )?(yang )?(mau )?(kamu |anda )?tanyakan", re.I), "CP3"),
    (re.compile(r"mau tanyakan apa lagi", re.I), "CP3b"),
    (re.compile(r"apakah ada hal lain", re.I), "CP2"),
    (re.compile(r"butuh bantuan apa", re.I), "CP4"),
    (re.compile(r"ada yang bisa (saya |aku )?bantu", re.I), "CP6"),
    (re.compile(r"anything else (i can|you('d| would) like)", re.I), "CP7"),
    (re.compile(r"how can i help", re.I), "CP8"),
    (re.compile(r"sebagai ai", re.I), "CP5"),
]


def score_cps(text: str) -> tuple[float, list[str]]:
    if not text:
        return 0.0, []
    hits: list[str] = []
    score = 0.0
    for pattern, code in CHATBOT_PATTERNS:
        if pattern.search(text):
            hits.append(code)
            score += 0.85
    return min(1.0, score), hits
