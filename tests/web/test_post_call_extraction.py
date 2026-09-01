"""Tests for post-call extraction persistence."""

from __future__ import annotations

from persona_ai.core.types import Message, PersonalityProfile
from persona_ai.runtime import PersonaRuntime
from persona_ai.session.models import SessionState
from persona_ai.session.store import InMemorySessionStore
from persona_ai.web.post_call_config import PostCallConfig
from persona_ai.web.post_call_extraction import extract_post_call_data


class _FakeClient:
    class models:
        @staticmethod
        def generate_content(*, model, contents, config):
            class _Resp:
                text = (
                    '{"call_summary":"User greeted the agent.",'
                    '"call_successful":true,"user_sentiment":"positive"}'
                )

            return _Resp()


def test_extract_and_persist_post_call(monkeypatch) -> None:
    store = InMemorySessionStore()
    profile = PersonalityProfile(id="t", preset_id="default_companion", display_name="Persona")
    runtime = PersonaRuntime(session_store=store, personality_profile=profile, llm_adapter=object())
    session = SessionState.new("live-test", profile_warmth=0.6)
    session.messages = [
        Message.from_text("user", "Halo Persona"),
        Message.from_text("assistant", "Hai! Senang bertemu kamu."),
    ]
    store.save(session)

    monkeypatch.setattr(
        "google.genai.Client",
        lambda api_key: _FakeClient(),
    )

    cfg = PostCallConfig()
    result = extract_post_call_data(
        runtime,
        "live-test",
        config=cfg,
        end_reason="session_end",
        duration_ms=60000,
        api_key="test-key",
    )
    assert result is not None
    assert result["data"]["call_successful"] is True
    saved = store.load("live-test")
    assert saved is not None
    assert saved.post_call is not None
    assert saved.post_call["data"]["user_sentiment"] == "positive"
