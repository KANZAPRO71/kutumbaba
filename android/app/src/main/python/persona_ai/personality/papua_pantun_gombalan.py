"""Pantun & gombalan Timur Papua — retrieval untuk mode cari maitua."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

_DATA_PATH = Path(__file__).parent / "data" / "papua_pantun_gombalan.json"

_QUERY_KEYWORDS = frozenset({
    "gombal", "gombalan", "pantun", "maitua", "pacar", "cinta", "sayang",
    "romantis", "manis", "nyatai", "modus", "rayu", "bucin", "jomblo",
})


@lru_cache(maxsize=1)
def _load_data() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def gombalan_count() -> int:
    items = _load_data().get("gombalan")
    return len(items) if isinstance(items, list) else 0


def _score_entry(query: str, keywords: list) -> int:
    q = _normalize(query)
    score = 0
    for kw in keywords:
        kw = str(kw).lower().strip()
        if kw and kw in q:
            score += 2
    return score


def retrieve_gombalan(query: str | None, *, limit: int = 3) -> list[str]:
    if not query or not query.strip():
        return []
    q = _normalize(query)
    if not any(k in q for k in _QUERY_KEYWORDS):
        return []

    data = _load_data()
    scored: list[tuple[int, str]] = []

    gombalan = data.get("gombalan")
    if isinstance(gombalan, list):
        for entry in gombalan:
            if not isinstance(entry, dict):
                continue
            kws = entry.get("keywords") or []
            if not isinstance(kws, list):
                continue
            score = _score_entry(q, kws)
            text = str(entry.get("text") or "").strip()
            if text and score > 0:
                scored.append((score, f"[Gombalan Timur] {text}"))

    pantun = data.get("pantun_timur")
    if isinstance(pantun, list):
        for entry in pantun:
            if not isinstance(entry, dict):
                continue
            kws = entry.get("keywords") or []
            if not isinstance(kws, list):
                continue
            score = _score_entry(q, kws)
            lines = entry.get("lines")
            if isinstance(lines, list) and score > 0:
                body = " / ".join(str(l).strip() for l in lines if str(l).strip())
                if body:
                    scored.append((score, f"[Pantun Timur] {body}"))

    scored.sort(key=lambda x: -x[0])
    return [text for _, text in scored[:limit]]


def pantun_gombalan_prompt_lines(
    dialect: str | None,
    *,
    language: str = "id",
    query: str | None = None,
    include_overview: bool = True,
) -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []

    data = _load_data()
    if not data:
        return []

    lines = [
        f"Pantun & gombalan Timur ({gombalan_count()} gombalan + pantun):",
        f"- {str(data.get('usage_note') or '').strip()}",
    ]

    if include_overview:
        gombalan = data.get("gombalan")
        if isinstance(gombalan, list):
            lines.append("- Gombalan siap pakai (variasi, jangan hafal persis):")
            for entry in gombalan[:3]:
                if not isinstance(entry, dict):
                    continue
                text = str(entry.get("text") or "").strip()
                if text:
                    lines.append(f"  · {text[:120]}{'…' if len(text) > 120 else ''}")

        tips = data.get("tips_cari_maitua")
        if isinstance(tips, list):
            for tip in tips[:2]:
                lines.append(f"  · {str(tip).strip()}")

    if query:
        hits = retrieve_gombalan(query, limit=2)
        if hits:
            lines.append("- Relevan gombal/pantun ko minta:")
            lines.extend(f"  · {h}" for h in hits)

    return lines
