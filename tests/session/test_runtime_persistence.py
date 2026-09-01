"""PersonaRuntime + session persistence tests — Phase 1 MVP."""

from __future__ import annotations

from pathlib import Path

import pytest

from persona_ai.conversation.pipeline_v0 import process_turn
from persona_ai.core.types import (
    BehaviorDirectiveVector,
    LLMRequest,
    LLMResponse,
    Message,
    PersonalityProfile,
    QuestionPolicy,
    ResponseLength,
    SpeakAction,
    TurnHistory,
)
from tests.support.stub_llm import StubLLMAdapter
from persona_ai.runtime import PersonaRuntime, _cap_question_budget
from persona_ai.session.models import SESSION_SCHEMA_VERSION, SessionState, deserialize_session, serialize_session
from persona_ai.session.store import InMemorySessionStore, SQLiteSessionStore


class SpyLLMAdapter:
    def __init__(self, inner: StubLLMAdapter | None = None) -> None:
        self.inner = inner or StubLLMAdapter()
        self.call_count = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        return self.inner.complete(request)


class FailingLLMAdapter:
    def complete(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("LLM unavailable")


@pytest.fixture
def memory_store() -> InMemorySessionStore:
    return InMemorySessionStore()


@pytest.fixture
def sqlite_store(tmp_path: Path) -> SQLiteSessionStore:
    return SQLiteSessionStore(tmp_path / "sessions.db")


@pytest.fixture
def profile() -> PersonalityProfile:
    return PersonalityProfile(warmth=0.6, formality=0.3)


class TestSessionSerialization:
    def test_schema_version_required(self):
        with pytest.raises(ValueError, match="schema_version"):
            deserialize_session({"session_id": "x", "arc": {"session_id": "x"}})

    def test_round_trip(self, profile: PersonalityProfile):
        runtime = PersonaRuntime(session_store=InMemorySessionStore(), personality_profile=profile)
        runtime.process_turn("ser", "Halo")
        loaded = runtime.session_store.load("ser")
        assert loaded is not None
        assert loaded.schema_version == SESSION_SCHEMA_VERSION
        payload = serialize_session(loaded)
        restored = deserialize_session(payload)
        assert restored.session_id == "ser"
        assert restored.turn_index == 1


class TestNewSession:
    def test_creates_persisted_session(self, memory_store: InMemorySessionStore, profile: PersonalityProfile):
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile)
        out = runtime.process_turn("s-new", "Besok meeting jam berapa?")
        assert out.text
        session = memory_store.load("s-new")
        assert session is not None
        assert session.turn_index == 1
        assert len(session.messages) == 2
        assert out.trace is not None
        assert out.trace.persistence_ok is True


class TestReload:
    def test_second_runtime_loads_same_session(self, sqlite_store: SQLiteSessionStore, profile: PersonalityProfile):
        db_path = sqlite_store._db_path
        r1 = PersonaRuntime(session_store=sqlite_store, personality_profile=profile)
        r1.process_turn("reload", "Halo")

        r2 = PersonaRuntime(
            session_store=SQLiteSessionStore(db_path),
            personality_profile=profile,
        )
        session = r2.session_store.load("reload")
        assert session is not None
        assert session.turn_index == 1
        assert session.messages[0].text == "Halo"


class TestHistoryPersists:
    def test_turn_one_visible_to_turn_two(self, memory_store: InMemorySessionStore, profile: PersonalityProfile):
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile)
        runtime.process_turn("hist", "Besok meeting jam berapa?")
        out2 = runtime.process_turn("hist", "Oke")
        session = memory_store.load("hist")
        assert session is not None
        assert len(session.messages) >= 2
        assert any(m.role == "user" and "Besok meeting" in m.text for m in session.messages)
        assert session.turn_history.last_speaker == "assistant" or out2.voice.speak == SpeakAction.SILENCE


class TestArcPersists:
    def test_arc_survives_reload(self, sqlite_store: SQLiteSessionStore, profile: PersonalityProfile):
        db_path = sqlite_store._db_path
        runtime = PersonaRuntime(session_store=sqlite_store, personality_profile=profile)
        runtime.process_turn("arc", "Halo")
        runtime.process_turn("arc", "Ah capek banget hari ini ya...")

        reloaded = PersonaRuntime(session_store=SQLiteSessionStore(db_path), personality_profile=profile)
        session = reloaded.session_store.load("arc")
        assert session is not None
        assert session.arc.turn_count == 2
        assert session.arc.turn_count > 0


class TestAnchorPersists:
    def test_anchor_affects_second_turn(self, memory_store: InMemorySessionStore, profile: PersonalityProfile):
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile)
        out1 = runtime.process_turn("anchor", "Ah capek banget hari ini ya...")
        session1 = memory_store.load("anchor")
        assert session1 is not None
        baseline1 = session1.anchor.session_tone_baseline

        out2 = runtime.process_turn("anchor", "Hmm…")
        session2 = memory_store.load("anchor")
        assert session2 is not None
        assert session2.anchor.session_tone_baseline != baseline1 or out2.voice.effective_warmth >= profile.warmth - 0.25
        assert out1.anchor is not None


class TestClosureAfterReload:
    def test_oke_silence_after_long_assistant(self, memory_store: InMemorySessionStore, profile: PersonalityProfile):
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile)
        long_text = " ".join(["detail"] * 120)
        session = memory_store.load("closure") or SessionState.new("closure", profile_warmth=profile.warmth)
        session.turn_history = TurnHistory(
            last_assistant_word_count=120,
            last_assistant_verbosity=ResponseLength.EXPAND,
            consecutive_assistant_turns=1,
        )
        session.messages.append(Message.from_text("assistant", long_text))
        memory_store.save(session)

        out = runtime.process_turn("closure", "Oke")
        assert out.text is None
        assert out.voice.speak == SpeakAction.SILENCE

        reloaded = PersonaRuntime(session_store=memory_store, personality_profile=profile)
        session_after = reloaded.session_store.load("closure")
        assert session_after is not None
        assert session_after.turn_index == 1


class TestDeferPersists:
    def test_mid_thought_defer(self, memory_store: InMemorySessionStore, profile: PersonalityProfile):
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile)
        out = runtime.process_turn("defer", "Jadi rencananya...", voice_pause_ms=1200)
        assert out.voice.speak == SpeakAction.DEFER
        assert out.text is None
        session = memory_store.load("defer")
        assert session is not None
        assert session.turn_index == 1
        assert session.messages[-1].role == "user"


class TestEarlyExitNoLLM:
    def test_silence_never_calls_adapter(self, memory_store: InMemorySessionStore, profile: PersonalityProfile):
        spy = SpyLLMAdapter()
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile, llm_adapter=spy)
        session = SessionState.new("silent", profile_warmth=profile.warmth)
        session.turn_history = TurnHistory(
            last_assistant_word_count=200,
            last_assistant_verbosity=ResponseLength.EXPAND,
        )
        memory_store.save(session)

        out = runtime.process_turn("silent", "Oke")
        assert out.voice.speak == SpeakAction.SILENCE
        assert spy.call_count == 0

    def test_defer_never_calls_adapter(self, memory_store: InMemorySessionStore, profile: PersonalityProfile):
        spy = SpyLLMAdapter()
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile, llm_adapter=spy)
        out = runtime.process_turn("defer-no-llm", "Jadi rencananya...", voice_pause_ms=1200)
        assert out.voice.speak == SpeakAction.DEFER
        assert spy.call_count == 0


class TestAckOnlyNatural:
    def test_vent_uses_llm_not_canned_template(self, memory_store: InMemorySessionStore, profile: PersonalityProfile):
        spy = SpyLLMAdapter()
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile, llm_adapter=spy)
        out = runtime.process_turn("ack", "Ah capek banget hari ini ya...")
        assert out.text not in ("Berat ya.", "Iyaa, paham.", "Iya.")
        assert out.text
        assert spy.call_count == 1


class TestAlwaysAnswerPolicy:
    def test_raw_silence_becomes_natural_ack(
        self, memory_store: InMemorySessionStore, profile: PersonalityProfile
    ):
        spy = SpyLLMAdapter()
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile, llm_adapter=spy)
        session = SessionState.new("always-closure", profile_warmth=profile.warmth)
        session.turn_history = TurnHistory(
            last_assistant_word_count=120,
            last_assistant_verbosity=ResponseLength.EXPAND,
            consecutive_assistant_turns=1,
        )
        memory_store.save(session)

        out = runtime.process_turn(
            "always-closure",
            "Oke",
            channel="text",
            response_policy="always_answer",
        )

        assert out.raw_bdv.speak == SpeakAction.SILENCE
        assert out.effective_bdv.speak == SpeakAction.ACK_ONLY
        assert out.bdv.speak == SpeakAction.ACK_ONLY
        assert out.text not in ("Oke.", "Berat ya.", "Iyaa, paham.")
        assert out.text
        assert spy.call_count == 1

    def test_raw_defer_becomes_natural_ack(
        self, memory_store: InMemorySessionStore, profile: PersonalityProfile
    ):
        spy = SpyLLMAdapter()
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile, llm_adapter=spy)

        out = runtime.process_turn(
            "always-defer",
            "Jadi rencananya...",
            voice_pause_ms=1200,
            channel="voice",
            response_policy="always_answer",
        )

        assert out.raw_bdv.speak == SpeakAction.DEFER
        assert out.effective_bdv.speak == SpeakAction.ACK_ONLY
        assert out.text not in ("Lanjut, aku dengerin.", "Berat ya.", "Iyaa, paham.")
        assert out.text
        assert spy.call_count == 1

    def test_live_greeting_skips_llm_and_canned_ack(
        self, memory_store: InMemorySessionStore, profile: PersonalityProfile
    ):
        spy = SpyLLMAdapter()
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile, llm_adapter=spy)
        out = runtime.process_turn(
            "live-hi",
            "Halo.",
            channel="voice",
            response_policy="always_answer",
            generate_text=False,
        )
        assert out.bdv.speak == SpeakAction.RESPOND
        assert out.effective_bdv.speak == SpeakAction.RESPOND
        assert out.text is None
        assert out.llm_called is False
        assert spy.call_count == 0


class TestGovernedVoicePolicy:
    def test_live_voice_keeps_raw_silence(
        self, memory_store: InMemorySessionStore, profile: PersonalityProfile
    ):
        spy = SpyLLMAdapter()
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile, llm_adapter=spy)
        session = SessionState.new("governed-closure", profile_warmth=profile.warmth)
        session.turn_history = TurnHistory(
            last_assistant_word_count=120,
            last_assistant_verbosity=ResponseLength.EXPAND,
            consecutive_assistant_turns=1,
        )
        memory_store.save(session)

        out = runtime.process_turn(
            "governed-closure",
            "Oke",
            channel="voice",
            response_policy="governed",
            generate_text=False,
        )

        assert out.raw_bdv.speak == SpeakAction.SILENCE
        assert out.effective_bdv.speak == SpeakAction.SILENCE
        assert out.bdv.speak == SpeakAction.SILENCE
        assert out.text is None
        assert out.llm_called is False
        assert spy.call_count == 0
        assert out.policy_constraints is not None


class TestQuestionBudgetCap:
    def test_preset_zero_forbids_clarify_budget(self, profile: PersonalityProfile):
        bdv = BehaviorDirectiveVector(
            speak=SpeakAction.RESPOND,
            questions=QuestionPolicy.CLARIFY_ONLY,
            question_budget=1,
        )
        capped = _cap_question_budget(bdv, profile)
        assert capped.question_budget == 0
        assert capped.questions == QuestionPolicy.NONE


class TestRecordSpokenReply:
    def test_creates_session_and_dedupes(
        self, memory_store: InMemorySessionStore, profile: PersonalityProfile
    ):
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile)
        runtime.record_spoken_reply("live-1", "Kita tadi bahas masa depan AI.")
        runtime.record_spoken_reply("live-1", "Kita tadi bahas masa depan AI.")
        runtime.record_spoken_reply("live-1", "Kita tadi bahas masa depan AI. Mau lanjut?")
        session = memory_store.load("live-1")
        assert session is not None
        assistants = [m.text for m in session.messages if m.role == "assistant"]
        assert assistants == ["Kita tadi bahas masa depan AI. Mau lanjut?"]

    def test_asr_revision_replaces_last_assistant(
        self, memory_store: InMemorySessionStore, profile: PersonalityProfile
    ):
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile)
        runtime.record_spoken_reply("live-2", "Massa depan AI bagus.")
        runtime.record_spoken_reply("live-2", "Masa depan AI bagus.")
        session = memory_store.load("live-2")
        assert session is not None
        assistants = [m.text for m in session.messages if m.role == "assistant"]
        assert assistants == ["Masa depan AI bagus."]

    def test_latest_with_messages_returns_newest_talk(
        self, memory_store: InMemorySessionStore, profile: PersonalityProfile
    ):
        runtime = PersonaRuntime(session_store=memory_store, personality_profile=profile)
        runtime.record_spoken_reply("old", "Halo.")
        runtime.record_spoken_reply("new", "Kita lanjut topik AI.")
        latest = memory_store.latest_with_messages()
        assert latest is not None
        assert latest.session_id == "new"


class TestFailureSafety:
    def test_llm_failure_does_not_corrupt_session(
        self, memory_store: InMemorySessionStore, profile: PersonalityProfile
    ):
        runtime = PersonaRuntime(
            session_store=memory_store,
            personality_profile=profile,
            llm_adapter=FailingLLMAdapter(),
        )
        runtime.process_turn("safe", "Halo.", generate_text=False)
        before = memory_store.load("safe")
        assert before is not None
        assert before.turn_index == 1

        with pytest.raises(RuntimeError, match="LLM unavailable"):
            runtime.process_turn("safe", "Besok meeting jam berapa?")

        after = memory_store.load("safe")
        assert after is not None
        assert after.turn_index == 1
        assert runtime.last_trace is not None
        assert runtime.last_trace.persistence_ok is False


class TestPipelineCompat:
    def test_existing_e2e_tests_still_work(self):
        out = process_turn("s1", "Ah capek banget hari ini ya...")
        assert out.text not in ("Berat ya.", "Iyaa, paham.", "Iya.")
        assert out.text

        out = process_turn("s2", "Besok meeting jam berapa?")
        assert out.text

        hist = TurnHistory(last_assistant_word_count=200, last_assistant_verbosity=ResponseLength.EXPAND)
        out = process_turn("s3", "Oke", history=hist)
        assert out.text is None
