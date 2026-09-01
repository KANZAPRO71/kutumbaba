"""Wibawa Ondoafi/Ondofolo — karakter pemimpin adat & panggilan hormat Tabi."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

_DATA_PATH = Path(__file__).parent / "data" / "papua_ondo_wibawa.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _ondo_query(query: str | None) -> bool:
    if not query:
        return False
    q = query.lower()
    data = _load()
    kws = data.get("keywords") or []
    if isinstance(kws, list) and any(str(k).lower() in q for k in kws):
        return True
    return any(t in q for t in ("ondo", "ondoafi", "ondofolo", "khano", "obhe", "ulayat"))


def ondo_wibawa_prompt_lines(
    dialect: str | None,
    *,
    language: str = "id",
    query: str | None = None,
    include_overview: bool = True,
) -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []

    data = _load()
    if not data:
        return []

    lines = [
        "Wibawa Ondoafi / sesepuh Tabi (AI cermin tongkrongan asli — ko su ondo di Papua):",
        f"- {str(data.get('usage_note') or '').strip()}",
    ]

    if include_overview:
        for cl in (data.get("character_lines") or [])[:5]:
            lines.append(f"- {cl}")
        sal = data.get("salutations")
        if isinstance(sal, dict):
            openings = sal.get("sacred_openings")
            if isinstance(openings, list) and openings:
                lines.append(f"- Salam sakral: {', '.join(str(o) for o in openings[:3])}")
            honor = sal.get("honorifics")
            if isinstance(honor, list):
                for h in honor[:3]:
                    if isinstance(h, dict):
                        lines.append(f"  · {h.get('term')} = {h.get('meaning')}")

    if query and _ondo_query(query):
        facts = data.get("adat_facts") or []
        if isinstance(facts, list):
            lines.append("- Relevan adat:")
            for f in facts[:3]:
                lines.append(f"  · {f}")

    return lines
