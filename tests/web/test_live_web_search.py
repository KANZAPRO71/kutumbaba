from __future__ import annotations

from pathlib import Path

from persona_ai.web.live_web_search import (
    fetch_live_web_context_sync,
    format_web_context_for_steer,
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
    assert "sa/ko" in block.lower() or "Papuan" in block


def test_gemini_live_bridge_imports_live_mode_config():
    text = Path("src/persona_ai/web/gemini_live_bridge.py").read_text(encoding="utf-8")
    assert "from persona_ai.web.live_mode import LiveModeConfig" in text


def test_fetch_live_web_context_sync_skips_non_fresh():
    assert fetch_live_web_context_sync("Halo ko apa kabar?", "AIzaSy0123456789012345678901234567890") is None
