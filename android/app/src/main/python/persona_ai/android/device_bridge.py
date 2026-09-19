"""Call Android DeviceContextBridge from embedded Chaquopy (no-op on desktop)."""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

_BRIDGE_CLASS = "com.persona.ai.DeviceContextBridge"
_bridge = None
_bridge_checked = False


def _load_bridge():
    global _bridge, _bridge_checked
    if _bridge_checked:
        return _bridge
    _bridge_checked = True
    try:
        from java import jclass  # type: ignore[import-untyped]

        _bridge = jclass(_BRIDGE_CLASS)
    except Exception as exc:
        _log.debug("DeviceContextBridge unavailable: %s", exc)
        _bridge = None
    return _bridge


def call_static_json(method: str) -> str | None:
    bridge = _load_bridge()
    if bridge is None:
        return None
    fn = getattr(bridge, method, None)
    if fn is None:
        return None
    try:
        result = fn()
        if result is None:
            return None
        return str(result)
    except Exception as exc:
        _log.warning("DeviceContextBridge.%s failed: %s", method, exc)
        return None
