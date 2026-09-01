"""Wilayah adat Tabi — Port Numbay (Jayapura) & Bhuvani (Sentani): marga & dialog lokal."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

_DATA_PATH = Path(__file__).parent / "data" / "papua_tabi_jayapura_sentani.json"

_RETRIEVE_LIMIT = 8
_CHAR_LIMIT = 160
_PROMPT_MARGA_SAMPLE = 6


@lru_cache(maxsize=1)
def _load_tabi() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=1)
def _marga_index() -> dict[str, dict[str, str]]:
    """Map marga name -> {kampung, lokasi, region}."""
    data = _load_tabi()
    index: dict[str, dict[str, str]] = {}

    hints = data.get("marga_locale_hints")
    if isinstance(hints, dict):
        for name, meta in hints.items():
            if isinstance(meta, dict):
                index[str(name)] = {
                    "kampung": str(meta.get("kampung") or ""),
                    "lokasi": str(meta.get("lokasi") or ""),
                    "region": str(meta.get("region") or ""),
                }

    port = data.get("port_numbay")
    if isinstance(port, dict):
        kampung_list = port.get("kampung")
        if isinstance(kampung_list, list):
            for kamp in kampung_list:
                if not isinstance(kamp, dict):
                    continue
                kname = str(kamp.get("name") or "")
                marga_list = kamp.get("marga")
                if not isinstance(marga_list, list):
                    continue
                for m in marga_list:
                    mstr = str(m).strip()
                    if mstr and mstr not in index:
                        index[mstr] = {
                            "kampung": kname.split("(")[0].strip() or kname,
                            "lokasi": "Teluk Youtefa" if "Tobati" in kname else "Jayapura",
                            "region": "port_numbay",
                        }

    sentani = data.get("sentani")
    if isinstance(sentani, dict):
        regions = sentani.get("regions")
        if isinstance(regions, list):
            for reg in regions:
                if not isinstance(reg, dict):
                    continue
                rname = str(reg.get("name") or "Sentani")
                marga_list = reg.get("marga")
                if not isinstance(marga_list, list):
                    continue
                for m in marga_list:
                    mstr = str(m).strip()
                    if mstr and mstr not in index:
                        index[mstr] = {
                            "kampung": rname,
                            "lokasi": "Danau Sentani",
                            "region": "sentani",
                        }

    return index


@lru_cache(maxsize=1)
def _all_marga_names() -> tuple[str, ...]:
    return tuple(sorted(_marga_index().keys(), key=len, reverse=True))


def marga_count() -> int:
    return len(_marga_index())


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _score_keywords(query: str, keywords: list[str]) -> int:
    q = _normalize(query)
    score = 0
    for kw in keywords:
        kw = kw.lower().strip()
        if not kw:
            continue
        if kw in q:
            score += 2 if " " in kw else 1
    return score


def detect_tabi_marga(text: str | None) -> str | None:
    """Deteksi marga Port Numbay atau Sentani dari obrolan user."""
    if not text or not text.strip():
        return None
    q = _normalize(text)
    for name in _all_marga_names():
        pattern = r"\b" + re.escape(name.lower()) + r"\b"
        if re.search(pattern, q):
            return name
    return None


def marga_response_hint(marga: str) -> str:
    data = _load_tabi()
    meta = _marga_index().get(marga, {})
    region = meta.get("region", "")
    kampung = meta.get("kampung", "Jayapura")
    lokasi = meta.get("lokasi", "Tabi")

    if region == "sentani":
        block = data.get("sentani")
        if isinstance(block, dict):
            template = str(block.get("detection_response_template") or "")
            if template and "{marga}" in template:
                return template.format(marga=marga, lokasi=lokasi or kampung)
        return (
            f"Iyo kah? Anak {marga} dari dusun sagu {lokasi} kah?! Siooo... "
            "salam hormat buat Ondoafi! Mari kitong baku hantam mop di pinggir danau, gasss!"
        )

    block = data.get("port_numbay")
    if isinstance(block, dict):
        template = str(block.get("detection_response_template") or "")
        if template and "{marga}" in template:
            return template.format(marga=marga, kampung=kampung)
    return (
        f"Adooo anak {marga} dari {kampung} kah?! Syowi kaka! "
        "Ko jangan berlagak tra tahu mendayung perahu di Teluk Youtefa ee, hahaha!"
    )


def retrieve_tabi_facts(query: str | None, *, limit: int = _RETRIEVE_LIMIT) -> list[str]:
    if not query or not query.strip():
        return []
    data = _load_tabi()
    out: list[str] = []

    detected = detect_tabi_marga(query)
    if detected:
        hint = marga_response_hint(detected)
        out.append(f"[Tabi — marga {detected}] {hint[:130]}…" if len(hint) > 130 else f"[Tabi — marga {detected}] {hint}")

    lead = data.get("leadership")
    if isinstance(lead, dict):
        kws = lead.get("keywords") or []
        facts = lead.get("facts") or []
        if isinstance(kws, list) and isinstance(facts, list) and _score_keywords(query, [str(k) for k in kws]) > 0:
            for fact in facts[:2]:
                out.append(f"[Tabi — adat] {fact}")

    port = data.get("port_numbay")
    if isinstance(port, dict):
        kws = port.get("keywords") or []
        if isinstance(kws, list) and _score_keywords(query, [str(k) for k in kws]) > 0:
            kampung_list = port.get("kampung")
            if isinstance(kampung_list, list):
                for kamp in kampung_list[:2]:
                    if not isinstance(kamp, dict):
                        continue
                    kname = str(kamp.get("name") or "")
                    marga_list = kamp.get("marga") or []
                    if kname and isinstance(marga_list, list):
                        sample = ", ".join(str(m) for m in marga_list[:5])
                        out.append(f"[Port Numbay — {kname}] Marga: {sample}…")

    sentani = data.get("sentani")
    if isinstance(sentani, dict):
        kws = sentani.get("keywords") or []
        if isinstance(kws, list) and _score_keywords(query, [str(k) for k in kws]) > 0:
            regions = sentani.get("regions")
            if isinstance(regions, list):
                for reg in regions[:2]:
                    if not isinstance(reg, dict):
                        continue
                    rname = str(reg.get("name") or "Sentani")
                    marga_list = reg.get("marga") or []
                    notes = str(reg.get("notes") or "")
                    if isinstance(marga_list, list):
                        sample = ", ".join(str(m) for m in marga_list[:5])
                        line = f"[Sentani — {rname}] Marga: {sample}. {notes}"
                        if len(line) > _CHAR_LIMIT:
                            line = line[: _CHAR_LIMIT - 1] + "…"
                        out.append(line)

    phrases = data.get("localization_phrases")
    if isinstance(phrases, list):
        for entry in phrases:
            if not isinstance(entry, dict):
                continue
            kws = entry.get("keywords") or []
            if isinstance(kws, list) and _score_keywords(query, [str(k) for k in kws]) > 0:
                phrase = str(entry.get("phrase") or "")
                meaning = str(entry.get("meaning") or "")
                if phrase and meaning:
                    out.append(f"[Frasa Tabi] {phrase} = {meaning}")

    return out[:limit]


def _tabi_query(query: str | None) -> bool:
    if not query:
        return False
    if detect_tabi_marga(query):
        return True
    q = _normalize(query)
    triggers = (
        "tabi", "port numbay", "numbay", "bhuvani", "sentani", "ondofolo", "ondoafi",
        "tobati", "youtefa", "kayobatu", "nafri", "skow mabo", "yoboi", "babrongko",
        "doyo", "dusun sagu", "taksi sentani", "pi spen di abe", "dok ii",
    )
    return any(t in q for t in triggers)


def tabi_prompt_lines(
    dialect: str | None,
    *,
    language: str = "id",
    query: str | None = None,
    include_overview: bool = True,
) -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []

    data = _load_tabi()
    if not data:
        return []

    lines = [
        f"Wilayah adat Tabi — Port Numbay & Bhuvani ({marga_count()} marga terdaftar):",
        f"- {str(data.get('usage_note') or '').strip()}",
        "- Ondofolo/Ondoafi = pemimpin adat; Mano (Tobati), Ohee (Doyo), Wally (Yoboi) = marga besar.",
        "- DETEKSI MARGA: user sebut Mano/Wally/dll — tanggap personal (Youtefa vs dusun sagu Sentani).",
        "- Frasa lokal: Anak Port Numbay, Pi Spen di Abe, Makan pinang di Dok II, Taksi Sentani.",
    ]

    if include_overview:
        port = data.get("port_numbay")
        if isinstance(port, dict):
            kampung_list = port.get("kampung")
            if isinstance(kampung_list, list) and kampung_list:
                first = kampung_list[0]
                if isinstance(first, dict):
                    marga_list = first.get("marga") or []
                    if isinstance(marga_list, list):
                        sample = ", ".join(str(m) for m in marga_list[:_PROMPT_MARGA_SAMPLE])
                        lines.append(f"- Tobati/Enggros (Youtefa): {sample}…")
        sentani = data.get("sentani")
        if isinstance(sentani, dict):
            regions = sentani.get("regions")
            if isinstance(regions, list) and regions:
                reg = regions[0]
                if isinstance(reg, dict):
                    marga_list = reg.get("marga") or []
                    if isinstance(marga_list, list):
                        sample = ", ".join(str(m) for m in marga_list[:_PROMPT_MARGA_SAMPLE])
                        lines.append(f"- Sentani Timur/Tengah: {sample}…")

    if query:
        detected = detect_tabi_marga(query)
        if detected:
            lines.append(f"- MARGA TERDETEKSI ({detected}): {marga_response_hint(detected)}")

    if query and (_tabi_query(query) or retrieve_tabi_facts(query, limit=1)):
        hits = retrieve_tabi_facts(query)
        if hits:
            lines.append("- Relevan obrolan ko sekarang:")
            lines.extend(f"  · {h}" for h in hits[:5])

    return lines
