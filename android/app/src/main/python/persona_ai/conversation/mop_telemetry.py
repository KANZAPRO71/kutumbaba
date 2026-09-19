"""MOP Engine telemetry — observer only."""

from __future__ import annotations

import json
import logging
from typing import Any

_log = logging.getLogger("persona_ai.mop.telemetry")


def log_mop_event(event: str, payload: dict[str, Any]) -> None:
    body = {"event": event, **payload}
    try:
        _log.info("mop_engine %s", json.dumps(body, ensure_ascii=False, default=str))
    except Exception:
        _log.info("mop_engine %r", body)
    try:
        from persona_ai.conversation.behavior_debug_store import get_behavior_debug_store

        get_behavior_debug_store().record("mop", event, payload)
    except Exception:
        pass
