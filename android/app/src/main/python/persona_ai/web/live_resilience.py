"""Link-state helpers for Gemini Live — separate from VAD/PCM capture."""

from __future__ import annotations

from enum import StrEnum
from typing import Callable

LINK_IDLE = "idle"
LINK_CONNECTED = "connected"
LINK_SUSPENDED = "suspended"
LINK_RESUMING = "resuming"
LINK_DISCONNECTED = "disconnected"
LINK_LIVE = "live"

SUSPEND_GRACE_S = 5.0
RESUME_MAX_ATTEMPTS_PER_MIN = 4


class LinkState(StrEnum):
    IDLE = LINK_IDLE
    CONNECTED = LINK_CONNECTED
    SUSPENDED = LINK_SUSPENDED
    RESUMING = LINK_RESUMING
    DISCONNECTED = LINK_DISCONNECTED
    LIVE = LINK_LIVE


def gov_set_link_state(gov: dict, state: str) -> None:
    gov["link_state"] = state


def gov_link_state(gov: dict) -> str:
    raw = gov.get("link_state")
    return str(raw) if raw else LINK_CONNECTED


def emit_link_state(enqueue: Callable[[dict], None], state: str, **extra: object) -> None:
    payload: dict = {"type": "link_state", "state": state}
    if extra:
        payload.update(extra)
    enqueue(payload)


def map_resume_to_link_states(
    *,
    starting: bool,
    success: bool,
    fatal: bool,
) -> list[str]:
    """Order of link_state events for Gemini session resumption."""
    if starting:
        return [LINK_RESUMING, LINK_SUSPENDED]
    if success:
        return [LINK_LIVE, LINK_CONNECTED]
    if fatal:
        return [LINK_DISCONNECTED]
    return []
