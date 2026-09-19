"""Thread-safe UI → asyncio hook for mid-call experience mode (Android WebView bridge)."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

ApplyModeFn = Callable[[str], Awaitable[None]]


@dataclass
class _LiveSessionRef:
    loop: asyncio.AbstractEventLoop
    apply_mode: ApplyModeFn
    last_applied: str


_lock = threading.Lock()
_session: _LiveSessionRef | None = None


def register_live_session(
    loop: asyncio.AbstractEventLoop,
    apply_mode: ApplyModeFn,
    *,
    initial_mode: str = "",
) -> None:
    global _session
    with _lock:
        _session = _LiveSessionRef(
            loop=loop,
            apply_mode=apply_mode,
            last_applied=(initial_mode or "").strip().lower(),
        )
    _log.debug("live_session_hub registered initial_mode=%s", initial_mode)


def unregister_live_session() -> None:
    global _session
    with _lock:
        _session = None


def request_mode_change_from_ui(mode: str) -> dict[str, Any]:
    key = (mode or "").strip().lower()
    if not key:
        return {"ok": False, "applied": False, "reason": "empty_mode"}
    with _lock:
        ref = _session
        if ref is None:
            return {"ok": True, "applied": False, "reason": "no_live_session", "mode": key}
        if ref.last_applied == key:
            return {"ok": True, "applied": False, "reason": "unchanged", "mode": key}
        ref.last_applied = key
        loop = ref.loop
        apply_fn = ref.apply_mode

    def _done(fut: asyncio.Future) -> None:
        try:
            fut.result()
        except Exception:
            _log.exception("native ui mode apply failed mode=%s", key)

    try:
        fut = asyncio.run_coroutine_threadsafe(apply_fn(key), loop)
        fut.add_done_callback(_done)
    except Exception:
        _log.exception("schedule native ui mode apply failed mode=%s", key)
        return {"ok": False, "applied": False, "reason": "schedule_failed", "mode": key}
    return {"ok": True, "applied": True, "reason": "scheduled", "mode": key}


def note_mode_applied_via_websocket(mode: str) -> None:
    """Keep hub in sync when browser WS already applied the switch (avoid duplicate)."""
    key = (mode or "").strip().lower()
    if not key:
        return
    with _lock:
        if _session is not None:
            _session.last_applied = key
