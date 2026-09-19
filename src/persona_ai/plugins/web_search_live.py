"""Gemini Live NON_BLOCKING web search tool (all sessions, not only embedded)."""

from __future__ import annotations

from typing import Any

from persona_ai.plugins.registry import register_tool
from persona_ai.web.live_web_search import (
    LIVE_WEB_SEARCH_TOOL_NAME,
    fetch_live_web_context_sync,
)

def non_blocking_live_tool_names() -> frozenset[str]:
    from persona_ai.plugins.registry import non_blocking_tool_names

    return non_blocking_tool_names()


def _search_web_for_user(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if len(query) < 3:
        return {"ok": False, "error": "missing_query", "found": False, "context": ""}
    api_key = str(ctx.get("api_key") or "").strip()
    if len(api_key) < 8:
        return {"ok": False, "error": "missing_api_key", "found": False, "context": ""}
    context = fetch_live_web_context_sync(query, api_key, force=True)
    if not context:
        return {
            "ok": True,
            "found": False,
            "context": "",
            "message": "Tidak ada hasil web yang cukup — jangan mengarang fakta.",
        }
    return {"ok": True, "found": True, "context": context}


register_tool(
    LIVE_WEB_SEARCH_TOOL_NAME,
    description=(
        "Cari info terbaru di web (berita, skor bola, cuaca, harga, politik, dll.). "
        "Panggil saat user minta kabar/skor/info hari ini yang butuh sumber web. "
        "NON_BLOCKING: lanjutkan obrolan singkat sambil menunggu hasil."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Pertanyaan atau topik pencarian singkat (Bahasa Indonesia).",
            }
        },
        "required": ["query"],
    },
    handler=_search_web_for_user,
)
