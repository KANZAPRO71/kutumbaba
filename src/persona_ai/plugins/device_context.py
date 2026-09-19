"""Device context tools — GPS snapshot & phone status (Android via Chaquopy)."""

from __future__ import annotations

import json
import time
from typing import Any

from persona_ai.plugins.registry import register_tool

_LOCATION_CACHE: tuple[float, dict[str, Any]] | None = None
_LOCATION_TTL_S = 45.0
_STATUS_CACHE: tuple[float, dict[str, Any]] | None = None
_STATUS_TTL_S = 15.0


def _read_android_json(method: str) -> dict[str, Any]:
    from persona_ai.android import device_bridge

    raw = device_bridge.call_static_json(method)
    if not raw:
        return {"ok": False, "error": "android_bridge_unavailable"}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"ok": False, "error": "invalid_json"}
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid_json"}


def _cached_location(_args: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    global _LOCATION_CACHE
    now = time.monotonic()
    if _LOCATION_CACHE and (now - _LOCATION_CACHE[0]) < _LOCATION_TTL_S:
        return dict(_LOCATION_CACHE[1])
    payload = _read_android_json("getLocationSnapshotJson")
    if payload.get("ok"):
        _LOCATION_CACHE = (now, payload)
    return payload


def _cached_device_status(_args: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    global _STATUS_CACHE
    now = time.monotonic()
    if _STATUS_CACHE and (now - _STATUS_CACHE[0]) < _STATUS_TTL_S:
        return dict(_STATUS_CACHE[1])
    payload = _read_android_json("getDeviceStatusJson")
    if payload.get("ok"):
        _STATUS_CACHE = (now, payload)
    return payload


register_tool(
    "get_location_snapshot",
    description=(
        "Read the user's approximate GPS on this Android phone (lat/long, accuracy, time). "
        "Use when they ask what is nearby, where they are walking, or location-aware questions. "
        "Combine with web search for place names — do not invent POIs. "
        "NON_BLOCKING: keep talking naturally (e.g. sebentar saya cek dulu) while this runs."
    ),
    parameters={"type": "object", "properties": {}},
    handler=_cached_location,
)

register_tool(
    "get_device_status",
    description=(
        "Read battery percentage, charging state, and network type on this Android phone. "
        "Use when the user asks about battery, charging, or connectivity."
    ),
    parameters={"type": "object", "properties": {}},
    handler=_cached_device_status,
)
