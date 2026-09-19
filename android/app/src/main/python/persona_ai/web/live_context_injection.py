"""Back-channel situational context via Live send_client_content (turn_complete=False)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from google.genai import types

_log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 30.0
POLL_INTERVAL_S = 5.0
MIN_INJECT_GAP_S = 18.0

_CONTEXT_PREFIX = "[SITUATIONAL_CONTEXT_UPDATE:"


def live_context_injection_enabled() -> bool:
    raw = os.environ.get("PERSONA_LIVE_CONTEXT_INJECT", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def read_android_telemetry() -> dict[str, Any]:
    from persona_ai.android.device_bridge import call_static_json

    raw = call_static_json("getTelemetryJson")
    if not raw:
        return {"ok": False, "error": "android_bridge_unavailable"}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"ok": False, "error": "invalid_json"}
    except json.JSONDecodeError:
        return {"ok": False, "error": "invalid_json"}


def _bucket_coord(value: float | int | None, step: float = 0.01) -> int:
    if value is None:
        return -9999
    try:
        return int(round(float(value) / step))
    except (TypeError, ValueError):
        return -9999


def telemetry_signature(telemetry: dict[str, Any]) -> str:
    """Coarse signature — inject when movement/battery/location bucket changes."""
    bat = telemetry.get("battery_percent", -1)
    mode = str(telemetry.get("movement_mode") or "")
    net = str(telemetry.get("network") or "")
    lat = _bucket_coord(telemetry.get("latitude"), 0.002)
    lon = _bucket_coord(telemetry.get("longitude"), 0.002)
    speed = int(float(telemetry.get("speed_kmh") or 0) // 5)
    return f"{lat}:{lon}:{mode}:{speed}:{bat}:{net}"


def build_context_summary(telemetry: dict[str, Any]) -> str | None:
    if not telemetry.get("ok"):
        return None
    parts: list[str] = []
    lat = telemetry.get("latitude")
    lon = telemetry.get("longitude")
    if lat is not None and lon is not None:
        parts.append(f"GPS {lat},{lon} (±{int(float(telemetry.get('accuracy_m') or 0))}m)")
    mode = telemetry.get("movement_mode")
    speed = telemetry.get("speed_kmh")
    if mode:
        sk = f"{float(speed):.0f}" if speed is not None else "0"
        parts.append(f"Gerak: {mode} ~{sk} km/h")
    bat = telemetry.get("battery_percent")
    if isinstance(bat, int) and bat >= 0:
        ch = "cas" if telemetry.get("charging") else "tra cas"
        parts.append(f"Baterai {bat}% ({ch})")
    net = telemetry.get("network")
    if net:
        parts.append(f"Jaringan: {net}")
    if not parts:
        return None
    return "; ".join(parts)


def format_context_turn_text(summary: str) -> str:
    clean = " ".join(summary.split())
    return f"{_CONTEXT_PREFIX} {clean}]"


async def inject_situational_context(
    session: object,
    session_send_lock: asyncio.Lock,
    summary: str,
) -> None:
    if not summary.strip():
        return
    text = format_context_turn_text(summary)
    turn = types.Content(role="user", parts=[types.Part(text=text)])
    async with session_send_lock:
        await session.send_client_content(turns=[turn], turn_complete=False)
    _log.info("live context injected len=%s", len(text))


async def situational_context_heartbeat(
    session: object,
    session_send_lock: asyncio.Lock,
    gov: dict,
    stop: asyncio.Event,
) -> None:
    """Embedded Android only — periodic back-channel without ending user turn."""
    if not live_context_injection_enabled():
        return
    last_sig = ""
    while not stop.is_set():
        await asyncio.sleep(POLL_INTERVAL_S)
        if stop.is_set():
            break
        if not gov.get("embedded_app"):
            continue
        if gov.get("gemini_resuming"):
            continue
        from persona_ai.web.live_pipeline_state import live_pipeline_idle

        if not live_pipeline_idle(gov):
            continue
        now = time.monotonic()
        last_at = float(gov.get("_context_last_inject_at") or 0.0)
        telemetry = await asyncio.to_thread(read_android_telemetry)
        sig = telemetry_signature(telemetry)
        sig_changed = sig != last_sig and sig != ""
        interval_ok = (now - last_at) >= HEARTBEAT_INTERVAL_S
        gap_ok = (now - last_at) >= MIN_INJECT_GAP_S
        if not ((interval_ok and gap_ok) or (sig_changed and gap_ok)):
            continue
        summary = build_context_summary(telemetry)
        if not summary:
            continue
        try:
            await inject_situational_context(session, session_send_lock, summary)
            gov["_context_last_inject_at"] = now
            gov["_context_last_sig"] = sig
            last_sig = sig
        except Exception:
            _log.exception("situational context inject failed")
