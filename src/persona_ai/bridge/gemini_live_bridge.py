"""Unified Async Live Engine — integration facade for Papua AI.

Blueprint name: ``PapuaAILiveEngine`` (single asyncio machine).

Production implementation is **not** a standalone ``websockets`` client. One
``handle_live_websocket`` session coordinates:

| Pillar | Blueprint sketch | Production module / hook |
|--------|------------------|---------------------------|
| 1 Async tools | ``_handle_async_tool`` + ``create_task`` | ``_spawn_live_tool_call`` → ``plugins/live_dispatch.py`` |
| 2 Context inject | ``send_dynamic_context`` | ``live_context_injection.py`` + ``sensor_monitor.py`` |
| 3 Mode meta | ``switch_experience_mode`` | ``apply_mid_call_experience_mode`` + ``live_mode_meta_injection.py`` |
| 4 Resiliency | State machine + jitter queue | ``resume_gemini`` + ``live_resilience.py``; playback jitter in ``static/live.js`` |

**Unchanged by design:** native PCM capture, VAD, turn detection, mic pacing.
Agent TTS is played in the **WebView AudioContext**, not Android ``AudioTrack``.

Experience modes manifest: ``persona_ai.conversation.experience_modes`` (not ``config/``).
"""

from __future__ import annotations

from typing import Final

# Canonical session entry (browser WebSocket ↔ PersonaRuntime ↔ Gemini Live SDK).
from persona_ai.web.gemini_live_bridge import (
    apply_mid_call_experience_mode,
    handle_live_websocket,
)

from persona_ai.web.live_resilience import (
    LINK_CONNECTED,
    LINK_DISCONNECTED,
    LINK_IDLE,
    LINK_LIVE,
    LINK_RESUMING,
    LINK_SUSPENDED,
    LinkState,
    SUSPEND_GRACE_S,
    emit_link_state,
    gov_link_state,
    gov_set_link_state,
    map_resume_to_link_states,
)

PILLAR_MODULES: Final[dict[str, str]] = {
    "async_tools": "persona_ai.plugins.registry + persona_ai.plugins.live_dispatch",
    "context_injection": "persona_ai.web.live_context_injection",
    "mode_meta": "persona_ai.web.live_mode_meta_injection",
    "resiliency": "persona_ai.web.live_resilience + persona_ai.web.static.live.js",
    "runtime": "persona_ai.web.gemini_live_bridge",
    "experience_modes": "persona_ai.conversation.experience_modes",
    "sensor_facade": "persona_ai.bridge.sensor_monitor",
}


class PapuaAILiveEngine:
    """Conceptual unified engine — maps blueprint API to production symbols.

    Do not instantiate for a second WS stack. The live call **is** the engine
    started by the FastAPI/Chaquopy server via ``handle_live_websocket``.
    """

    __slots__ = ()

    handle_live_websocket = staticmethod(handle_live_websocket)
    apply_mid_call_experience_mode = staticmethod(apply_mid_call_experience_mode)

    # Pillar 4 link-state vocabulary (browser UI via ``link_state`` JSON events).
    LinkState = LinkState
    LINK_IDLE = LINK_IDLE
    LINK_CONNECTED = LINK_CONNECTED
    LINK_SUSPENDED = LINK_SUSPENDED
    LINK_RESUMING = LINK_RESUMING
    LINK_DISCONNECTED = LINK_DISCONNECTED
    LINK_LIVE = LINK_LIVE
    SUSPEND_GRACE_S = SUSPEND_GRACE_S
    emit_link_state = staticmethod(emit_link_state)
    gov_set_link_state = staticmethod(gov_set_link_state)
    gov_link_state = staticmethod(gov_link_state)
    map_resume_to_link_states = staticmethod(map_resume_to_link_states)


__all__ = [
    "PILLAR_MODULES",
    "PapuaAILiveEngine",
    "apply_mid_call_experience_mode",
    "handle_live_websocket",
    "LinkState",
    "LINK_CONNECTED",
    "LINK_DISCONNECTED",
    "LINK_IDLE",
    "LINK_LIVE",
    "LINK_RESUMING",
    "LINK_SUSPENDED",
    "SUSPEND_GRACE_S",
    "emit_link_state",
    "gov_link_state",
    "gov_set_link_state",
    "map_resume_to_link_states",
]
