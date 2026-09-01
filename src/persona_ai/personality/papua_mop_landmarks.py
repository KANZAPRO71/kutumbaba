"""Ikon tempat nyata untuk lokalisasi cerita Mop Papua."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

_DATA_PATH = Path(__file__).parent / "data" / "papua_mop_landmarks.json"


@lru_cache(maxsize=1)
def _load_landmarks() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def landmark_prompt_lines(
    dialect: str | None,
    *,
    language: str = "id",
    query: str | None = None,
) -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []
    data = _load_landmarks()
    regions = data.get("regions")
    if not isinstance(regions, list):
        return []

    q = (query or "").lower()
    lines = [
        "Ikon tempat nyata (lokalisasi Mop — sebut nama tempat biar cerita terasa lokal):",
    ]

    matched = 0
    for region in regions:
        if not isinstance(region, dict):
            continue
        keywords = [str(k).lower() for k in (region.get("keywords") or [])]
        landmarks = region.get("landmarks")
        if not isinstance(landmarks, list):
            continue
        title = str(region.get("title") or region.get("id") or "Papua")
        if q and not any(kw in q for kw in keywords):
            continue
        lines.append(f"- {title}:")
        for item in landmarks[:4]:
            lines.append(f"  · {item}")
        matched += 1

    if matched == 0:
        for region in regions[:3]:
            if not isinstance(region, dict):
                continue
            title = str(region.get("title") or "Papua")
            landmarks = region.get("landmarks") or []
            if landmarks:
                lines.append(f"- {title}: {landmarks[0]}")

    return lines
