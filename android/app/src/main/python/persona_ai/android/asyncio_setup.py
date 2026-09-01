"""Asyncio bootstrap for Chaquopy on Android.

Gemini Live (websockets + google-genai) needs a running event loop on Python's
*main* thread. Uvicorn must therefore start on the same thread that called
Python.start() — see LocalPersonaServer in Kotlin.
"""

from __future__ import annotations

import asyncio
import logging

_log = logging.getLogger(__name__)


def ensure_event_loop() -> asyncio.AbstractEventLoop:
    """Create/set the thread-local event loop if missing (Android/Chaquopy)."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _log.info("asyncio: created event loop on thread %s", _thread_label())
        return loop

    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _log.info("asyncio: replaced closed loop on thread %s", _thread_label())
    return loop


def _thread_label() -> str:
    import threading

    return threading.current_thread().name


def patch_uvicorn_for_embedded() -> None:
    """Prefer stdlib asyncio loop — uvloop is not available on Android."""
    ensure_event_loop()
