"""Tests for Retell Webhook Settings mapping."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from persona_ai.core.types import PersonalityProfile
from persona_ai.web.webhook_config import DEFAULT_WEBHOOK_EVENTS, LiveWebhookConfig
from persona_ai.web.webhook_delivery import (
    build_call_object,
    build_webhook_payload,
    deliver_webhook_event,
    resolve_webhook_url,
    sample_test_call,
)


def test_defaults_match_retell_webhook_settings() -> None:
    cfg = LiveWebhookConfig()
    assert cfg.webhook_url is None
    assert cfg.webhook_timeout_ms == 5000
    assert cfg.webhook_events == DEFAULT_WEBHOOK_EVENTS
    assert not cfg.enabled


def test_from_profile_reads_live_webhook_block() -> None:
    profile = PersonalityProfile(id="t", preset_id="default_companion", display_name="Persona")
    cfg = LiveWebhookConfig.from_profile(profile)
    assert cfg.webhook_timeout_ms == 5000
    assert "call_started" in cfg.webhook_events
    assert "call_ended" in cfg.webhook_events
    assert "call_analyzed" in cfg.webhook_events


def test_should_emit_respects_event_filter() -> None:
    cfg = LiveWebhookConfig(
        webhook_url="https://example.com/hook",
        webhook_events=("call_ended",),
    )
    assert cfg.should_emit("call_ended")
    assert not cfg.should_emit("call_started")


def test_resolve_webhook_url_with_dynamic_variables() -> None:
    cfg = LiveWebhookConfig(webhook_url="https://example.com/hook?agent={{agent_name}}")
    url = resolve_webhook_url(cfg, {"agent_name": "Persona"})
    assert url == "https://example.com/hook?agent=Persona"


def test_build_webhook_payload_retell_shape() -> None:
    call = sample_test_call()
    payload = build_webhook_payload("call_started", call)
    assert payload["event"] == "call_started"
    assert payload["call"]["call_id"] == "test-call"
    assert payload["call"]["call_status"] == "ongoing"


def test_deliver_skips_when_disabled() -> None:
    cfg = LiveWebhookConfig()
    result = deliver_webhook_event(cfg, event="call_started", call=build_call_object(
        session_id="s1", agent_id="a1", call_status="ongoing"
    ))
    assert result["skipped"] is True


def test_deliver_posts_json() -> None:
    cfg = LiveWebhookConfig(
        webhook_url="https://example.com/hook",
        webhook_timeout_ms=5000,
    )
    mock_resp = MagicMock()
    mock_resp.status = 204
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("persona_ai.web.webhook_delivery.urllib.request.urlopen", return_value=mock_resp):
        result = deliver_webhook_event(
            cfg,
            event="call_started",
            call=sample_test_call(),
        )
    assert result["ok"] is True
    assert result["status_code"] == 204
