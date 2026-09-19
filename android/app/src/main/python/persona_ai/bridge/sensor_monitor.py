"""Sensor / telemetry facade (Pillar 2) — blueprint ``send_dynamic_context``.

Periodic injection during an active call is handled by
``situational_context_heartbeat`` (started inside ``handle_live_websocket``).
Use this module for one-off reads or manual back-channel sends from tests/tools.
"""

from __future__ import annotations

import asyncio

from persona_ai.web.live_context_injection import (
    build_context_summary,
    inject_situational_context,
    live_context_injection_enabled,
    read_android_telemetry,
)


def live_sensor_monitor_enabled() -> bool:
    return live_context_injection_enabled()


def fetch_sensor_snapshot() -> dict:
    """GPS / battery / network snapshot from ``DeviceContextBridge`` (embedded Android)."""
    return read_android_telemetry()


def build_dynamic_context_summary(telemetry: dict | None = None) -> str | None:
    data = telemetry if telemetry is not None else fetch_sensor_snapshot()
    return build_context_summary(data)


async def send_dynamic_context(
    session: object,
    session_send_lock: asyncio.Lock,
    context_summary: str,
) -> None:
    """Inject ``[SITUATIONAL_CONTEXT_UPDATE: …]`` with ``turn_complete=False``."""
    await inject_situational_context(session, session_send_lock, context_summary)


__all__ = [
    "build_dynamic_context_summary",
    "fetch_sensor_snapshot",
    "live_sensor_monitor_enabled",
    "send_dynamic_context",
]
