"""WebView @JavascriptInterface → Python (experience mode, no PCM/VAD touch)."""

from __future__ import annotations

import logging
import re
from typing import Any

_log = logging.getLogger(__name__)

# Blueprint / marketing ids from mock UI → canonical experience_mode id.
_UI_MODE_ALIASES: dict[str, str] = {
    "radio_story": "story",
    "radio_stories": "story",
    "story": "story",
    "teman_jalan": "teman_jalan",
    "teman_jalan_mode": "teman_jalan",
    "belajar_baku": "study",
    "belajar": "study",
    "study": "study",
    "cerita_aja": "cerita_tong",
    "cerita_tong": "cerita_tong",
    "nongkrong": "nongkrong",
    "mop": "mop",
    "teman_malam": "teman_malam",
}


def _slug(mode_raw: str) -> str:
    text = (mode_raw or "").strip().lower()
    text = re.sub(r"[\s\-]+", "_", text)
    return re.sub(r"[^a-z0-9_]", "", text)


def normalize_ui_mode(mode_raw: str | None) -> str:
    from persona_ai.conversation.experience_modes import normalize_experience_mode

    slug = _slug(mode_raw or "")
    if not slug:
        return normalize_experience_mode(None)
    mapped = _UI_MODE_ALIASES.get(slug, slug)
    return normalize_experience_mode(mapped)


def on_app_lifecycle(event: str) -> dict[str, Any]:
    """Android MainActivity lifecycle hook (Chaquopy thread)."""
    name = (event or "").strip().lower()
    if name == "destroy":
        try:
            from persona_ai.web.live_session_hub import unregister_live_session

            unregister_live_session()
        except Exception:
            _log.debug("live_session_hub unregister on destroy", exc_info=True)
    _log.debug("app lifecycle event=%s", name)
    return {"ok": True, "event": name}


def handle_ui_mode_change(mode_raw: str) -> dict[str, Any]:
    """Called from Kotlin PersonaAndroid.onModeChanged (Chaquopy background thread).

    During an active voice call, ``app.js`` also sends ``conversation_mode`` over the
    browser WebSocket — that path applies mid-call meta injection. This handler
    normalizes the id, records telemetry, and optionally forwards to a live session
    when the WebSocket message did not arrive (fallback).
    """
    mode = normalize_ui_mode(mode_raw)
    _log.info("webview ui mode change raw=%r normalized=%s", mode_raw, mode)
    applied = False
    reason = "normalized_only"
    try:
        from persona_ai.web.live_session_hub import request_mode_change_from_ui

        result = request_mode_change_from_ui(mode)
        applied = bool(result.get("applied"))
        reason = str(result.get("reason") or reason)
    except Exception:
        _log.debug("live_session_hub unavailable", exc_info=True)
    return {"ok": True, "mode": mode, "applied": applied, "reason": reason}
