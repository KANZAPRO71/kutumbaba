"""Turn timing telemetry — pre-LLM latency instrumentation."""

from __future__ import annotations

from persona_ai.core.types import PersonalityProfile
from tests.support.stub_llm import StubLLMAdapter
from persona_ai.runtime import PersonaRuntime
from persona_ai.session.store import InMemorySessionStore


class TestTurnTiming:
    def test_silence_has_pre_llm_timing_no_llm_ms(self):
        runtime = PersonaRuntime(
            session_store=InMemorySessionStore(),
            personality_profile=PersonalityProfile(),
            llm_adapter=StubLLMAdapter(),
        )
        long_assistant = " ".join(["word"] * 80)
        runtime.process_turn("t1", "warm up")
        runtime.process_turn("t1", long_assistant)
        out = runtime.process_turn("t1", "Oke")
        assert out.timing is not None
        assert out.timing.pre_llm_ms >= 0
        assert out.timing.llm_ms is None
        assert out.trace is not None
        assert out.trace.timing is out.timing

    def test_respond_includes_llm_ms(self):
        runtime = PersonaRuntime(
            session_store=InMemorySessionStore(),
            llm_adapter=StubLLMAdapter(),
        )
        out = runtime.process_turn("t2", "Besok meeting jam berapa?")
        assert out.timing is not None
        assert out.timing.llm_ms is not None
        assert out.timing.llm_ms >= 0
        assert out.timing.pre_llm_ms >= 0
        assert out.timing.total_ms >= out.timing.pre_llm_ms
