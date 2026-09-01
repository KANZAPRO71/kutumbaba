"""Gemini Interactions adapter tests — mocked client, no network."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from persona_ai.core.types import (
    LLMRequest,
    Message,
    PolicyConstraintsRef,
    PersonalityProfile,
    SpeakAction,
    ToneShift,
    VoiceDirective,
)
from persona_ai.llm.gemini import (
    GeminiAdapterError,
    GeminiCredentialsError,
    GeminiEmptyOutputError,
    GeminiLLMAdapter,
)
from persona_ai.llm.interactions_history import build_interactions_input
from persona_ai.llm.prompt import build_system_prompt
from persona_ai.runtime import PersonaRuntime
from persona_ai.session.store import InMemorySessionStore


def _voice(**kwargs) -> VoiceDirective:
    defaults = dict(
        speak=SpeakAction.RESPOND,
        effective_warmth=0.6,
        max_words=30,
        max_sentences=2,
        question_budget=0,
        tone_shift=ToneShift.STABLE,
        prompt_fragments=["Do not ask closing offers."],
    )
    defaults.update(kwargs)
    return VoiceDirective(**defaults)


@dataclass
class FakeInteraction:
    output_text: str
    usage: object | None = None


class TestInteractionsHistory:
    def test_builds_user_and_model_steps(self):
        history = [
            Message.from_text("user", "Halo"),
            Message.from_text("assistant", "Hai."),
        ]
        steps = build_interactions_input(history, "Besok meeting jam berapa?")
        assert steps[0]["type"] == "user_input"
        assert steps[0]["content"][0]["type"] == "text"
        assert steps[1]["type"] == "model_output"
        assert steps[-1]["type"] == "user_input"
        assert steps[-1]["content"][0]["text"] == "Besok meeting jam berapa?"


class TestGeminiAdapterMocked:
    def setup_method(self) -> None:
        self.create = MagicMock(return_value=FakeInteraction("Gemini says hi."))
        self.client = MagicMock()
        self.client.interactions.create = self.create
        self.adapter = GeminiLLMAdapter(
            model="gemini-test-model",
            api_key="test-key",
            client=self.client,
        )

    def test_respond_calls_interactions_once(self):
        voice = _voice()
        text = self.adapter.render(voice, "Besok meeting jam berapa?", history=[])
        assert text == "Gemini says hi."
        self.create.assert_called_once()
        kwargs = self.create.call_args.kwargs
        assert kwargs["model"] == "gemini-test-model"
        assert kwargs["store"] is False
        assert kwargs["input"][-1]["type"] == "user_input"
        assert "system_instruction" in kwargs
        assert "Max words" in kwargs["system_instruction"]
        assert "cqf" not in kwargs["system_instruction"].lower()

    def test_history_passed_as_steps(self):
        history = [Message.from_text("user", "Halo"), Message.from_text("assistant", "Hai.")]
        self.adapter.render(_voice(), "Follow up?", history=history)
        steps = self.create.call_args.kwargs["input"]
        assert len(steps) == 3
        assert steps[0]["type"] == "user_input"
        assert steps[1]["type"] == "model_output"

    def test_policy_constraints_in_system_instruction(self):
        req = LLMRequest(
            user_message="hi",
            voice=_voice(),
            policy_constraints=PolicyConstraintsRef(inject_system_lines=["Crisis line."]),
        )
        self.adapter.complete(req)
        system = self.create.call_args.kwargs["system_instruction"]
        assert "Crisis line." in system

    def test_empty_output_raises(self):
        self.create.return_value = FakeInteraction("")
        with pytest.raises(GeminiEmptyOutputError):
            self.adapter.render(_voice(), "hello")

    def test_api_failure_raises_typed_error(self):
        self.create.side_effect = RuntimeError("network down")
        with pytest.raises(GeminiAdapterError, match="Gemini Interactions call failed"):
            self.adapter.render(_voice(), "hello")

    def test_missing_credentials(self):
        adapter = GeminiLLMAdapter(api_key="")
        with pytest.raises(GeminiCredentialsError):
            adapter.render(_voice(), "hello")


class TestBehaviorPathsNoGeminiCall:
    @pytest.mark.parametrize(
        "session_id,user_text,kwargs,expect_speak",
        [
            ("silent", "Oke", {}, SpeakAction.SILENCE),
            ("defer", "Jadi rencananya...", {"voice_pause_ms": 1200}, SpeakAction.DEFER),
        ],
    )
    def test_no_interactions_call(self, session_id, user_text, kwargs, expect_speak):
        create = MagicMock(return_value=FakeInteraction("should not appear"))
        client = MagicMock()
        client.interactions.create = create
        adapter = GeminiLLMAdapter(model="gemini-test-model", api_key="k", client=client)
        runtime = PersonaRuntime(
            session_store=InMemorySessionStore(),
            personality_profile=PersonalityProfile(),
            llm_adapter=adapter,
        )
        if session_id == "silent":
            from persona_ai.core.types import ResponseLength, TurnHistory
            from persona_ai.session.models import SessionState

            session = SessionState.new(session_id, profile_warmth=0.6)
            session.turn_history = TurnHistory(
                last_assistant_word_count=200,
                last_assistant_verbosity=ResponseLength.EXPAND,
            )
            runtime.session_store.save(session)

        out = runtime.process_turn(session_id, user_text, **kwargs)
        assert out.voice.speak == expect_speak
        create.assert_not_called()


class TestRuntimeIntegrationGemini:
    def test_respond_with_policy_intact(self):
        create = MagicMock(return_value=FakeInteraction("Sebagai AI, besok jam 9."))
        client = MagicMock()
        client.interactions.create = create
        adapter = GeminiLLMAdapter(model="gemini-test-model", api_key="k", client=client)
        store = InMemorySessionStore()
        runtime = PersonaRuntime(session_store=store, llm_adapter=adapter)

        out = runtime.process_turn("gem", "Besok meeting jam berapa?")
        create.assert_called_once()
        assert out.bdv is not None
        assert out.bdv.speak == SpeakAction.RESPOND
        assert out.text
        assert "sebagai ai" not in out.text.lower()
        assert out.policy_result is not None
        session = store.load("gem")
        assert session is not None
        assert session.turn_index == 1

    def test_gemini_failure_does_not_commit(self):
        create = MagicMock(side_effect=RuntimeError("Gemini down"))
        client = MagicMock()
        client.interactions.create = create
        adapter = GeminiLLMAdapter(model="gemini-test-model", api_key="k", client=client)
        store = InMemorySessionStore()
        runtime = PersonaRuntime(session_store=store, llm_adapter=adapter)
        runtime.process_turn("fail-gem", "Halo.", generate_text=False)
        before = store.load("fail-gem")
        assert before is not None
        assert before.turn_index == 1

        with pytest.raises(GeminiAdapterError):
            runtime.process_turn("fail-gem", "Besok meeting jam berapa?")

        after = store.load("fail-gem")
        assert after is not None
        assert after.turn_index == 1


class TestPromptPurityGemini:
    def test_system_prompt_has_no_diagnostics_leakage(self):
        req = LLMRequest(user_message="hi", voice=_voice())
        prompt = build_system_prompt(req)
        for forbidden in ("cqf", "cps", "arbitration", "diagnostics", "manifold", "forecast"):
            assert forbidden not in prompt.lower()
