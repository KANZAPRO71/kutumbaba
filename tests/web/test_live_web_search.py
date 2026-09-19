from __future__ import annotations

from pathlib import Path

from google.genai import types

from persona_ai.plugins.live_dispatch import live_session_tools
from persona_ai.plugins.registry import invoke_tool
from persona_ai.web.live_web_search import (
    LIVE_WEB_SEARCH_TOOL_NAME,
    fetch_live_web_context_sync,
    format_web_context_for_steer,
    live_async_web_search_enabled,
    needs_live_web_search,
)


def test_needs_live_web_search_detects_news():
    assert needs_live_web_search("Berita Papua terbaru hari ini apa?")
    assert needs_live_web_search("Skor bola Indonesia kemarin berapa?")


def test_needs_live_web_search_skips_geo_only():
    assert not needs_live_web_search("Cerita tentang Papua dong ko")
    assert not needs_live_web_search("Ko dari Indonesia ya")


def test_needs_live_web_search_skips_mop_and_memory():
    assert not needs_live_web_search("Ceritain mop lucu dong")
    assert not needs_live_web_search("Apa arti pu dalam kamus?")


def test_needs_live_web_search_skips_short():
    assert not needs_live_web_search("halo ko")


def test_format_web_context_for_steer_papua():
    block = format_web_context_for_steer("Hasil: 2-1", dialect="papua")
    assert "KONTEKS WEB TERBARU" in block
    assert "ko belum nemu" in block.lower()


def test_gemini_live_bridge_imports_live_mode_config():
    text = Path("src/persona_ai/web/gemini_live_bridge.py").read_text(encoding="utf-8")
    assert "from persona_ai.web.live_mode import LiveModeConfig" in text


def test_fetch_live_web_context_sync_skips_non_fresh():
    assert fetch_live_web_context_sync("Halo ko apa kabar?", "AIzaSy0123456789012345678901234567890") is None


def test_fetch_live_web_context_sync_force_bypasses_needs_heuristic(monkeypatch):
    calls = {"n": 0}

    def _fake_search(query: str, api_key: str, model: str):
        calls["n"] += 1
        return "Hasil uji", []

    monkeypatch.setattr("persona_ai.web.live_web_search._gemini_search_sync", _fake_search)
    out = fetch_live_web_context_sync(
        "Halo ko",
        "AIzaSy0123456789012345678901234567890",
        force=True,
    )
    assert calls["n"] == 1
    assert out and "Hasil uji" in out


def test_live_async_web_search_default_on():
    assert live_async_web_search_enabled() is True


def test_live_session_tools_web_search_non_blocking():
    tools = live_session_tools(embedded_app=False, async_web_search=True)
    assert tools is not None
    decls = tools[0].function_declarations or []
    names = {d.name for d in decls}
    assert LIVE_WEB_SEARCH_TOOL_NAME in names
    web_decl = next(d for d in decls if d.name == LIVE_WEB_SEARCH_TOOL_NAME)
    assert web_decl.behavior == types.Behavior.NON_BLOCKING


def test_web_search_tool_handler_missing_query():
    from persona_ai.plugins import web_search_live  # noqa: F401

    payload = invoke_tool(LIVE_WEB_SEARCH_TOOL_NAME, {}, {"api_key": "AIzaSy0123456789012345678901234567890"})
    assert payload.get("ok") is False
