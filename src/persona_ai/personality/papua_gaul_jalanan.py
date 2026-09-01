"""Slang gaul jalanan Jayapura — Yombex, tangkisan pamer, full-duplex."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

_DATA_PATH = Path(__file__).parent / "data" / "papua_gaul_jalanan.json"

_PAMER_ITEM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bhp\b|\bhandphone\b|\bandroid\b|\biphone\b", "HP baru"),
    (r"sepatu", "sepatu baru"),
    (r"baju|kaos|jaket", "baju baru"),
    (r"motor|mobil", "kendaraan baru"),
    (r"pacar", "pacar baru"),
)


@lru_cache(maxsize=1)
def _load_gaul() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def gaul_word_count() -> int:
    words = _load_gaul().get("words")
    return len(words) if isinstance(words, list) else 0


def detect_pamer(text: str | None) -> bool:
    if not text or not text.strip():
        return False
    data = _load_gaul()
    triggers = data.get("pamer_triggers")
    if not isinstance(triggers, list):
        return False
    q = _normalize(text)
    return any(str(t).lower() in q for t in triggers)


def _guess_pamer_item(text: str) -> str:
    q = _normalize(text)
    for pattern, label in _PAMER_ITEM_PATTERNS:
        if re.search(pattern, q):
            return label
    return "barang baru"


def yombex_pamer_response(text: str | None) -> str | None:
    if not detect_pamer(text):
        return None
    data = _load_gaul()
    template = str(data.get("yombex_pamer_response") or "")
    if not template or "{item}" not in template:
        return (
            "Adooo paceee... ko yombex setengah mati ee! Baru dapat barang baru saja su pamer di sa. "
            "Ko jangan berlagak dulu, mending kasi menyala mikrofon baru kitong baku balas mop, hahaha! Gasss!"
        )
    return template.format(item=_guess_pamer_item(text or ""))


def slang_barge_in_entries() -> list[dict]:
    items = _load_gaul().get("slang_barge_in")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def detect_baku_tangkis(text: str | None) -> str | None:
    """Deteksi trigger baku tangkis — return response template jika match."""
    if not text or not text.strip():
        return None
    q = _normalize(text)
    for entry in slang_barge_in_entries():
        triggers = entry.get("user_triggers")
        if not isinstance(triggers, list):
            continue
        response = str(entry.get("response") or "").strip()
        if not response:
            continue
        for trigger in triggers:
            t = str(trigger).lower().strip()
            if t and t in q:
                if "{item}" in response:
                    return response.format(item=_guess_pamer_item(text))
                return response
    return None


def baku_tangkis_mode_lines() -> list[str]:
    data = _load_gaul()
    mode = data.get("baku_tangkis_mode")
    if not isinstance(mode, dict):
        return []
    lines = [f"{str(mode.get('title') or 'Baku Tangkis Slang')}:"]
    desc = str(mode.get("description") or "").strip()
    if desc:
        lines.append(f"- {desc}")
    rules = mode.get("rules")
    if isinstance(rules, list):
        for rule in rules[:4]:
            lines.append(f"  · {str(rule).strip()}")
    return lines


def retrieve_gaul_facts(query: str | None, *, limit: int = 6) -> list[str]:
    if not query or not query.strip():
        return []
    q = _normalize(query)
    out: list[str] = []

    if detect_pamer(query):
        resp = yombex_pamer_response(query)
        if resp:
            out.append(f"[Yombex pamer] {resp}")

    words = _load_gaul().get("words")
    if isinstance(words, list):
        for entry in words:
            if not isinstance(entry, dict):
                continue
            kws = entry.get("keywords") or []
            if not isinstance(kws, list):
                continue
            if any(str(k).lower() in q for k in kws):
                word = str(entry.get("word") or "")
                meaning = str(entry.get("meaning") or "")
                example = str(entry.get("example") or "")
                line = f"[Gaul Jayapura] {word} = {meaning}"
                if example:
                    line += f" — contoh: {example}"
                if len(line) > 180:
                    line = line[:179] + "…"
                out.append(line)

    return out[:limit]


def gaul_jalanan_prompt_lines(
    dialect: str | None,
    *,
    language: str = "id",
    query: str | None = None,
    include_overview: bool = True,
) -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []

    data = _load_gaul()
    if not data:
        return []

    lines = [
        f"Slang gaul jalanan Jayapura / Port Numbay ({gaul_word_count()} kata kunci):",
        f"- {str(data.get('usage_note') or '').strip()}",
        "- Yombex = sombong/berlagak/pamer (Jayapura) — Ih, yombex paling parah!",
        "- Sekelas: Epen (emang penting?), Kalkota (mbual), Kombas (geng), Sakar (pelit), Akur (setuju gasss).",
        "- User pamer HP/baju/motor/pacar → potong cepat: Adooo paceee... ko yombex setengah mati ee!",
        *baku_tangkis_mode_lines(),
    ]

    if include_overview:
        words = data.get("words")
        if isinstance(words, list):
            for entry in words[:5]:
                if not isinstance(entry, dict):
                    continue
                word = str(entry.get("word") or "")
                meaning = str(entry.get("meaning") or "")
                if word and meaning:
                    lines.append(f"  · {word} = {meaning}")

    if query and detect_pamer(query):
        resp = yombex_pamer_response(query)
        if resp:
            lines.append(f"- PAMER TERDETEKSI → jawab: {resp}")

    if query:
        tangkis = detect_baku_tangkis(query)
        if tangkis and not detect_pamer(query):
            lines.append(f"- BAKU TANGKIS → potong balas: {tangkis}")

    if query:
        hits = retrieve_gaul_facts(query, limit=3)
        if hits and not detect_pamer(query):
            lines.append("- Relevan slang:")
            lines.extend(f"  · {h}" for h in hits)

    return lines
