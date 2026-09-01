"""Optional live Gemini smoke — skipped without GEMINI_API_KEY."""

from __future__ import annotations

import os

import pytest

from persona_ai import PersonaRuntime
from persona_ai.llm.gemini import GeminiLLMAdapter
from persona_ai.session.store import InMemorySessionStore

pytestmark = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)


@pytest.mark.live_gemini
def test_live_gemini_respond():
    runtime = PersonaRuntime(
        session_store=InMemorySessionStore(),
        llm_adapter=GeminiLLMAdapter(),
    )
    out = runtime.process_turn("live-gemini", "Besok meeting jam berapa? Jawab singkat.")
    assert out.text
    assert out.llm_called is True
