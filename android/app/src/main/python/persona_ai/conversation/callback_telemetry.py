"""Callback gate telemetry — observer only."""

from __future__ import annotations

import json
import logging
from typing import Any

_log = logging.getLogger("persona_ai.callback.telemetry")


def log_callback_event(event: str, payload: dict[str, Any]) -> None:
    body = {"event": event, **payload}
    try:
        _log.info("callback_gate %s", json.dumps(body, ensure_ascii=False, default=str))
    except Exception:
        _log.info("callback_gate %r", body)
    try:
        from persona_ai.conversation.behavior_debug_store import get_behavior_debug_store

        get_behavior_debug_store().record("callback", event, payload)
    except Exception:
        pass
