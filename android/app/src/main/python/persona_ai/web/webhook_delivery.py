"""Deliver Retell-compatible webhook events to agent-level URLs."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Mapping

from persona_ai.web.dynamic_variables import substitute_dynamic_variables
from persona_ai.web.webhook_config import LiveWebhookConfig

_log = logging.getLogger(__name__)


def _utc_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def build_call_object(
    *,
    session_id: str,
    agent_id: str | None,
    call_status: str,
    duration_ms: int = 0,
    end_reason: str | None = None,
    voice_name: str | None = None,
    language_code: str | None = None,
    call_analysis: dict[str, Any] | None = None,
    transcript: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "call_id": session_id,
        "agent_id": agent_id,
        "call_status": call_status,
        "duration_ms": duration_ms,
        "start_timestamp": _utc_ms() - max(duration_ms, 0),
    }
    if end_reason:
        payload["disconnection_reason"] = end_reason
    if voice_name:
        payload["voice_name"] = voice_name
    if language_code:
        payload["language_code"] = language_code
    if call_analysis is not None:
        payload["call_analysis"] = call_analysis
    if transcript is not None:
        payload["transcript"] = transcript
    return payload


def build_webhook_payload(event: str, call: Mapping[str, Any]) -> dict[str, Any]:
    return {"event": event, "call": dict(call)}


def resolve_webhook_url(config: LiveWebhookConfig, dynamic_variables: Mapping[str, str]) -> str | None:
    if not config.webhook_url:
        return None
    return substitute_dynamic_variables(config.webhook_url, dynamic_variables)


def deliver_webhook_event(
    config: LiveWebhookConfig,
    *,
    event: str,
    call: Mapping[str, Any],
    dynamic_variables: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """POST a Retell-shaped event. Returns delivery metadata (never raises)."""
    if not config.should_emit(event):
        return {"ok": False, "skipped": True, "reason": "event_not_subscribed", "event": event}

    url = resolve_webhook_url(config, dynamic_variables or {})
    if not url:
        return {"ok": False, "skipped": True, "reason": "no_webhook_url", "event": event}

    body = json.dumps(build_webhook_payload(event, call), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Persona-AI-Webhook/1.0"},
        method="POST",
    )
    timeout_s = config.webhook_timeout_ms / 1000.0
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return {
                "ok": True,
                "event": event,
                "url": url,
                "status_code": resp.status,
                "elapsed_ms": elapsed_ms,
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _log.warning("webhook HTTP error event=%s status=%s url=%s", event, exc.code, url)
        return {
            "ok": False,
            "event": event,
            "url": url,
            "status_code": exc.code,
            "elapsed_ms": elapsed_ms,
            "error": str(exc.reason),
        }
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _log.warning("webhook delivery failed event=%s url=%s err=%s", event, url, exc)
        return {
            "ok": False,
            "event": event,
            "url": url,
            "elapsed_ms": elapsed_ms,
            "error": str(exc),
        }


def sample_test_call(*, session_id: str = "test-call", agent_id: str | None = "default_companion") -> dict[str, Any]:
    """Sample payload for Retell dashboard Test button parity."""
    return build_call_object(
        session_id=session_id,
        agent_id=agent_id,
        call_status="ongoing",
        duration_ms=0,
        voice_name="Sulafat",
        language_code="id-ID",
    )
