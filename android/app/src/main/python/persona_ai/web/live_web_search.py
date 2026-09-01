"""Deteksi pertanyaan info terbaru + Google Search grounding untuk Gemini Live."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

_log = logging.getLogger(__name__)

# Wajib ada sinyal waktu/berita — bukan sekadar menyebut Papua/Indonesia.
_TIME_NEWS_HINTS = re.compile(
    r"\b("
    r"terbaru|terkini|hari\s+ini|kemarin|minggu\s+ini|bulan\s+ini|tahun\s+ini|"
    r"berita|update|kabar|info\s+terbaru|"
    r"skor|hasil\s+pertandingan|pertandingan|sepak\s*bola|bola|liga|"
    r"menang|kalah|juara|"
    r"presiden|pemerintah|dpr|politik|pemilu|"
    r"cuaca\s+sekarang|harga\s+terbaru|"
    r"who\s+won|latest|news|today|score|match"
    r")\b",
    re.IGNORECASE,
)

_EXCLUDE = re.compile(
    r"\b("
    r"ingat\s+ya|apa\s+arti|artinya|maksudnya|mop|pantun|gombal|kamus|"
    r"ceritain\s+mop|lelucon|logat|bahasa\s+papua|ngobrol|halo|apa\s+kabar"
    r")\b",
    re.IGNORECASE,
)

_SEARCH_FALLBACK_MODEL = "gemini-2.0-flash"
_SEARCH_TIMEOUT_S = 8.0


def needs_live_web_search(query: str) -> bool:
    """True when user clearly asks for fresh web info (news, scores, etc.)."""
    q = (query or "").strip()
    if len(q) < 10:
        return False
    if _EXCLUDE.search(q):
        return False
    return bool(_TIME_NEWS_HINTS.search(q))


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text and str(text).strip():
        return str(text).strip()
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        chunks = [str(getattr(p, "text", "") or "") for p in parts if getattr(p, "text", None)]
        if chunks:
            return "\n".join(chunks).strip()
    return ""


def _extract_grounding(response: Any) -> list[str]:
    snippets: list[str] = []
    for cand in getattr(response, "candidates", None) or []:
        gm = getattr(cand, "grounding_metadata", None)
        if not gm:
            continue
        for q in getattr(gm, "web_search_queries", None) or []:
            snippets.append(f"Pencarian: {q}")
        for ch in (getattr(gm, "grounding_chunks", None) or [])[:5]:
            web = getattr(ch, "web", None)
            if not web:
                continue
            title = (getattr(web, "title", None) or "").strip()
            uri = (getattr(web, "uri", None) or "").strip()
            if title or uri:
                snippets.append(f"- {title} ({uri})".strip())
    return snippets


def _duckduckgo_fallback_sync(query: str) -> str | None:
    try:
        import httpx
    except ImportError:
        return None
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            resp = client.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query.strip(),
                    "format": "json",
                    "no_redirect": 1,
                    "skip_disambig": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        _log.debug("duckduckgo fallback failed: %s", exc)
        return None

    parts: list[str] = []
    abstract = (data.get("AbstractText") or "").strip()
    heading = (data.get("Heading") or "").strip()
    if abstract:
        prefix = f"{heading}: " if heading else ""
        parts.append(f"{prefix}{abstract}")
    for topic in (data.get("RelatedTopics") or [])[:4]:
        if isinstance(topic, dict):
            text = (topic.get("Text") or "").strip()
            if text:
                parts.append(f"- {text}")
    if not parts:
        return None
    return "\n".join(parts)


def _gemini_search_sync(query: str, api_key: str, model: str) -> tuple[str, list[str]]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key.strip())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    prompt = (
        f"Pertanyaan user (obrolan suara Papua AI): {query.strip()}\n\n"
        f"Cari info terbaru di web (sekitar {now}). "
        "Ringkas 3-6 poin fakta penting dalam Bahasa Indonesia — siap dibacakan AI suara. "
        "Sertakan tanggal/waktu kalau ada. Jangan mengarang."
    )
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
        ),
    )
    return _extract_text(response), _extract_grounding(response)


def fetch_live_web_context_sync(
    query: str,
    api_key: str,
    *,
    model: str | None = None,
    _allow_fallback_model: bool = True,
) -> str | None:
    if not needs_live_web_search(query):
        return None
    if not api_key or len(api_key.strip()) < 8:
        return None

    from persona_ai.llm.gemini_models import gemini_text_model

    use_model = model or gemini_text_model()
    body = ""
    grounding: list[str] = []
    try:
        body, grounding = _gemini_search_sync(query, api_key, use_model)
    except Exception as exc:
        _log.warning("live web search failed model=%s: %s", use_model, exc)
        if _allow_fallback_model and use_model != _SEARCH_FALLBACK_MODEL:
            try:
                body, grounding = _gemini_search_sync(query, api_key, _SEARCH_FALLBACK_MODEL)
            except Exception as exc2:
                _log.warning("live web search fallback model failed: %s", exc2)

    if not body and not grounding:
        body = _duckduckgo_fallback_sync(query) or ""

    if not body and not grounding:
        return None

    parts = ["[HASIL CARI WEB — pakai untuk jawab user, jangan mengarang di luar ini]"]
    if body:
        parts.append(body)
    if grounding:
        parts.append("Sumber:")
        parts.extend(grounding[:6])
    return "\n".join(parts)


async def fetch_live_web_context(query: str, api_key: str) -> str | None:
    import asyncio

    return await asyncio.to_thread(fetch_live_web_context_sync, query, api_key)


def format_web_context_for_steer(context: str, *, dialect: str | None = None) -> str:
    from persona_ai.personality.papua_dialect_phrases import is_papua_dialect, papua_steer_reminder

    lines = [
        "[KONTEKS WEB TERBARU — wajib dipakai, jangan mengarang]",
        context.strip(),
        "Jawab user pakai info di atas. Kalau kurang lengkap, bilang jujur ko belum nemu detailnya.",
    ]
    if is_papua_dialect(dialect):
        lines.append(papua_steer_reminder())
    return "\n".join(lines)


SEARCH_TIMEOUT_S = _SEARCH_TIMEOUT_S
