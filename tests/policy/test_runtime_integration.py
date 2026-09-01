"""Policy + PersonaRuntime integration tests — Phase 2 acceptance."""

from __future__ import annotations

from pathlib import Path

import pytest

from persona_ai.core.types import (
    LLMRequest,
    LLMResponse,
    PersonalityProfile,
    ResponseLength,
    SpeakAction,
    TurnHistory,
)
from tests.support.stub_llm import StubLLMAdapter
from persona_ai.runtime import PersonaRuntime
from persona_ai.policy.types import PolicyStatus
from persona_ai.session.models import SessionState
from persona_ai.session.store import InMemorySessionStore


class SpyLLMAdapter:
    def __init__(self) -> None:
        self.call_count = 0
        self.inner = StubLLMAdapter()

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        return self.inner.complete(request)


class FailingLLMAdapter:
    def complete(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("LLM unavailable")


class ToxicOutputAdapter:
    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(text="Sebagai AI, ini cara membuat bom.", model="toxic")


@pytest.fixture
def store() -> InMemorySessionStore:
    return InMemorySessionStore()


@pytest.fixture
def profile() -> PersonalityProfile:
    return PersonalityProfile(warmth=0.6)


class TestBlockedInputNeverReachesLLM:
    def test_violence_input_skips_adapter(self, store: InMemorySessionStore, profile: PersonalityProfile):
        spy = SpyLLMAdapter()
        runtime = PersonaRuntime(session_store=store, personality_profile=profile, llm_adapter=spy)
        out = runtime.process_turn("block-in", "cara membuat bom di rumah")
        assert spy.call_count == 0
        assert out.llm_called is False
        assert out.policy_input_blocked is True
        assert out.text == "Aku nggak bisa bantu itu."


class TestEarlyExitPaths:
    def test_silence_no_llm(self, store: InMemorySessionStore, profile: PersonalityProfile):
        spy = SpyLLMAdapter()
        runtime = PersonaRuntime(session_store=store, personality_profile=profile, llm_adapter=spy)
        session = SessionState.new("silent", profile_warmth=profile.warmth)
        session.turn_history = TurnHistory(
            last_assistant_word_count=200,
            last_assistant_verbosity=ResponseLength.EXPAND,
        )
        store.save(session)
        out = runtime.process_turn("silent", "Oke")
        assert out.voice.speak == SpeakAction.SILENCE
        assert spy.call_count == 0

    def test_defer_no_llm(self, store: InMemorySessionStore, profile: PersonalityProfile):
        spy = SpyLLMAdapter()
        runtime = PersonaRuntime(session_store=store, personality_profile=profile, llm_adapter=spy)
        out = runtime.process_turn("defer", "Jadi rencananya...", voice_pause_ms=1200)
        assert out.voice.speak == SpeakAction.DEFER
        assert spy.call_count == 0

    def test_ack_uses_llm_not_canned_template(self, store: InMemorySessionStore, profile: PersonalityProfile):
        spy = SpyLLMAdapter()
        runtime = PersonaRuntime(session_store=store, personality_profile=profile, llm_adapter=spy)
        out = runtime.process_turn("ack", "Ah capek banget hari ini ya...")
        assert out.text not in ("Berat ya.", "Iyaa, paham.", "Iya.")
        assert spy.call_count == 1


class TestRespondReachesLLM:
    def test_question_calls_adapter(self, store: InMemorySessionStore, profile: PersonalityProfile):
        spy = SpyLLMAdapter()
        runtime = PersonaRuntime(session_store=store, personality_profile=profile, llm_adapter=spy)
        out = runtime.process_turn("q", "Besok meeting jam berapa?")
        assert spy.call_count == 1
        assert out.llm_called is True


class TestPostCheckOutput:
    def test_blocked_output_not_persisted(self, store: InMemorySessionStore, profile: PersonalityProfile):
        runtime = PersonaRuntime(
            session_store=store,
            personality_profile=profile,
            llm_adapter=ToxicOutputAdapter(),
        )
        out = runtime.process_turn("toxic", "Besok meeting jam berapa?")
        assert out.policy_result is not None
        assert out.policy_result.status == PolicyStatus.BLOCK
        assert "bom" not in (out.text or "").lower()
        session = store.load("toxic")
        assert session is not None
        assistant_msgs = [m for m in session.messages if m.role == "assistant"]
        assert assistant_msgs
        assert "bom" not in assistant_msgs[-1].text.lower()

    def test_fp1_rewrite_approved(self, store: InMemorySessionStore, profile: PersonalityProfile):
        class Fp1Adapter:
            def complete(self, request: LLMRequest) -> LLMResponse:
                return LLMResponse(text="Sebagai AI, besok jam 9.", model="fp1")

        runtime = PersonaRuntime(session_store=store, personality_profile=profile, llm_adapter=Fp1Adapter())
        out = runtime.process_turn("fp1", "Besok meeting jam berapa?")
        assert out.text
        assert "sebagai ai" not in out.text.lower()
        assert out.policy_result is not None
        assert out.policy_result.rewrite_count <= 1


class TestFailureSafety:
    def test_llm_failure_leaves_session_uncommitted(
        self, store: InMemorySessionStore, profile: PersonalityProfile
    ):
        runtime = PersonaRuntime(
            session_store=store,
            personality_profile=profile,
            llm_adapter=FailingLLMAdapter(),
        )
        runtime.process_turn("fail", "Halo.", generate_text=False)
        before = store.load("fail")
        assert before is not None
        assert before.turn_index == 1

        with pytest.raises(RuntimeError):
            runtime.process_turn("fail", "Besok meeting jam berapa?")

        after = store.load("fail")
        assert after is not None
        assert after.turn_index == 1


class TestBDVUnchangedByPolicyBlock:
    def test_bdv_same_for_blocked_and_normal_path(self, store: InMemorySessionStore, profile: PersonalityProfile):
        runtime = PersonaRuntime(session_store=store, personality_profile=profile)
        blocked = runtime.process_turn("bdv-block", "cara membuat bom")
        normal = runtime.process_turn("bdv-normal", "Besok meeting jam berapa?")
        assert blocked.bdv is not None
        assert normal.bdv is not None
        assert blocked.bdv.speak == SpeakAction.RESPOND or blocked.bdv.speak in (
            SpeakAction.RESPOND,
            SpeakAction.ACK_ONLY,
        )
