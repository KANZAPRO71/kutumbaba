"""Structured turn/session metrics for Experience Mode validation."""

from __future__ import annotations

import json
import logging
from typing import Any

_log = logging.getLogger("persona_ai.experience.telemetry")


def log_session_summary(payload: dict[str, Any]) -> None:
    """One row per voice session — supports cross-session consistency in eval."""
    try:
        _log.info(
            "experience_session %s",
            json.dumps(payload, ensure_ascii=False, default=str),
        )
    except Exception:
        _log.info("experience_session %r", payload)
    try:
        from persona_ai.conversation.behavior_debug_store import get_behavior_debug_store

        get_behavior_debug_store().record("experience", "session_summary", payload)
    except Exception:
        pass


def log_turn_metric(payload: dict[str, Any]) -> None:
    """Info-level JSON line — grep-friendly in device logs."""
    try:
        _log.info("experience_turn %s", json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:
        _log.info("experience_turn %r", payload)
    try:
        from persona_ai.conversation.behavior_debug_store import get_behavior_debug_store

        get_behavior_debug_store().record("experience", "turn", payload)
    except Exception:
        pass
