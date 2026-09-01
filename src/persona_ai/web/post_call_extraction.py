"""Retell-style post-call data extraction after voice sessions."""

from __future__ import annotations

import json
import logging
from typing import Any

from persona_ai.runtime import PersonaRuntime
from persona_ai.web.persona_live import load_session_messages
from persona_ai.web.post_call_config import PostCallConfig
from persona_ai.web.security_config import LiveSecurityConfig

_log = logging.getLogger(__name__)


def _format_transcript(messages: list, security_cfg: LiveSecurityConfig | None = None) -> str:
    lines: list[str] = []
    for msg in messages:
        role = "User" if msg.role == "user" else "Agent"
        text = " ".join((msg.text or "").split())
        if security_cfg is not None:
            text = security_cfg.redact_text(text)
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)


def _build_prompt(
    *,
    transcript: str,
    config: PostCallConfig,
    end_reason: str,
    duration_ms: int,
) -> str:
    field_lines = "\n".join(
        f"- {field.id} ({field.name}): {field.description or field.type}"
        for field in config.fields
    )
    schema = json.dumps(config.json_schema(), ensure_ascii=False)
    return (
        "Extract structured post-call analytics from this voice conversation.\n"
        f"Call ended because: {end_reason}\n"
        f"Call duration_ms: {duration_ms}\n\n"
        "Fields to extract:\n"
        f"{field_lines}\n\n"
        f"Return JSON matching this schema exactly:\n{schema}\n\n"
        "Transcript:\n"
        f"{transcript}"
    )


def extract_post_call_data(
    runtime: PersonaRuntime,
    session_id: str,
    *,
    config: PostCallConfig,
    end_reason: str = "session_end",
    duration_ms: int = 0,
    api_key: str | None = None,
    security_cfg: LiveSecurityConfig | None = None,
) -> dict[str, Any] | None:
    """Run Gemini extraction and persist on the session."""
    if not config.enabled:
        return None
    messages = load_session_messages(runtime, session_id)
    transcript = _format_transcript(messages, security_cfg)
    if not transcript.strip():
        _log.info("post-call extraction skipped — empty transcript session=%s", session_id)
        return None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        _log.warning("google-genai missing — post-call extraction skipped")
        return None

    key = api_key
    if not key and hasattr(runtime.llm_adapter, "api_key"):
        key = runtime.llm_adapter.api_key
    if not key:
        _log.warning("no API key — post-call extraction skipped")
        return None

    prompt = _build_prompt(
        transcript=transcript,
        config=config,
        end_reason=end_reason,
        duration_ms=duration_ms,
    )
    client = genai.Client(api_key=key)
    model = config.model_name()
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        raw = (response.text or "").strip()
        if not raw:
            _log.warning("post-call extraction empty response session=%s", session_id)
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("post-call extraction did not return a JSON object")
    except Exception:
        _log.exception("post-call extraction failed session=%s model=%s", session_id, model)
        return None

    payload = {
        "session_id": session_id,
        "end_reason": end_reason,
        "duration_ms": duration_ms,
        "model": model,
        "data": data,
    }
    runtime.record_post_call_data(session_id, payload)
    _log.info("post-call extraction saved session=%s keys=%s", session_id, list(data.keys()))
    return payload
