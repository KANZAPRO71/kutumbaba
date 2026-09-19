"""Unified bridge facade imports and blueprint mapping."""

from persona_ai.bridge import (
    PILLAR_MODULES,
    apply_mid_call_experience_mode,
    handle_live_websocket,
    send_dynamic_context,
)
from persona_ai.bridge.gemini_live_bridge import PapuaAILiveEngine
from persona_ai.web.live_resilience import LINK_CONNECTED, LinkState


def test_pillar_modules_cover_runtime():
    assert "runtime" in PILLAR_MODULES
    assert "gemini_live_bridge" in PILLAR_MODULES["runtime"]


def test_papua_engine_aliases_production_entry():
    assert PapuaAILiveEngine.handle_live_websocket is handle_live_websocket
    assert PapuaAILiveEngine.apply_mid_call_experience_mode is apply_mid_call_experience_mode
    assert PapuaAILiveEngine.LinkState is LinkState
    assert PapuaAILiveEngine.LINK_CONNECTED == LINK_CONNECTED


def test_sensor_facade_callable():
    assert callable(send_dynamic_context)
