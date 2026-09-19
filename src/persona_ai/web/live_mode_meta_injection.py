"""Dynamic experience-mode meta prompt — send_client_content without reconnect."""

from __future__ import annotations

import asyncio
import logging
import os

from google.genai import types

_log = logging.getLogger(__name__)


def live_meta_inject_enabled() -> bool:
    raw = os.environ.get("PERSONA_LIVE_META_INJECT", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")

_META_PREFIX = "[META_SYSTEM_OVERRIDE:"


def format_meta_override_turn(steer_body: str) -> str:
    """Wrap mid-session steer as a non-turn system override (not user speech)."""
    body = " ".join((steer_body or "").split())
    return f"{_META_PREFIX} {body}]"


async def inject_experience_mode_meta(
    session: object,
    session_send_lock: asyncio.Lock,
    steer_text: str,
) -> None:
    if not (steer_text or "").strip():
        return
    text = format_meta_override_turn(steer_text)
    turn = types.Content(role="user", parts=[types.Part(text=text)])
    async with session_send_lock:
        await session.send_client_content(turns=[turn], turn_complete=False)
    _log.info("experience mode meta injected chars=%s", len(text))
