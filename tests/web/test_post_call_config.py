"""Tests for Retell post-call data extraction config."""

from __future__ import annotations

from persona_ai.core.types import Message, PersonalityProfile
from persona_ai.web.post_call_config import PostCallConfig


def test_default_retell_fields() -> None:
    cfg = PostCallConfig()
    ids = {field.id for field in cfg.fields}
    assert ids == {"call_summary", "call_successful", "user_sentiment"}
    schema = cfg.json_schema()
    assert set(schema["required"]) == ids
    assert schema["properties"]["user_sentiment"]["enum"] == [
        "positive",
        "neutral",
        "negative",
    ]


def test_from_profile_reads_live_post_call() -> None:
    profile = PersonalityProfile(id="t", preset_id="default_companion", display_name="Persona")
    cfg = PostCallConfig.from_profile(profile)
    assert cfg.enabled is True
    assert cfg.model_name() == "gemini-3.1-flash-lite-preview"
    assert len(cfg.fields) == 3


def test_custom_field_from_dict() -> None:
    cfg = PostCallConfig.from_dict(
        {
            "enabled": True,
            "fields": [
                {
                    "id": "topic",
                    "name": "Main Topic",
                    "type": "string",
                    "description": "Primary topic discussed",
                }
            ],
        }
    )
    assert len(cfg.fields) == 1
    assert cfg.fields[0].id == "topic"


def test_build_prompt_includes_transcript() -> None:
    from persona_ai.web.post_call_extraction import _build_prompt

    cfg = PostCallConfig()
    prompt = _build_prompt(
        transcript="User: Halo\nAgent: Hai!",
        config=cfg,
        end_reason="session_end",
        duration_ms=120000,
    )
    assert "call_summary" in prompt
    assert "User: Halo" in prompt
