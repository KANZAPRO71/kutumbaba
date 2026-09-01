"""Modul Suku Biak — Keret, Ararem, Wor samudra, Wós Vyak, dialog interaktif."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

_DATA_PATH = Path(__file__).parent / "data" / "papua_biak_wosvyak.json"

_RETRIEVE_LIMIT = 8
_PROMPT_VOCAB_LIMIT = 8
_PROMPT_KERET_LIMIT = 8
_CHAR_LIMIT = 160


@lru_cache(maxsize=1)
def _load_biak() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=1)
def _all_keret_names() -> tuple[str, ...]:
    data = _load_biak()
    keret = data.get("keret")
    if not isinstance(keret, dict):
        return ()
    names: list[str] = []
    for key in ("marga_populer", "marga_auwr_kuno"):
        items = keret.get(key)
        if isinstance(items, list):
            names.extend(str(x).strip() for x in items if str(x).strip())
    return tuple(dict.fromkeys(names))


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


def usage_note() -> str:
    data = _load_biak()
    note = data.get("usage_note")
    return str(note).strip() if note else "Seling Wós Vyak sedikit-sedikit — terjemahkan singkat dalam kurung."


def vocabulary_count() -> int:
    vocab = _load_biak().get("vocabulary")
    return len(vocab) if isinstance(vocab, list) else 0


def keret_count() -> int:
    return len(_all_keret_names())


def detect_keret(text: str | None) -> str | None:
    """Deteksi marga Biak (keret) dari nama atau obrolan user."""
    if not text or not text.strip():
        return None
    q = _normalize(text)
    # Prioritas marga panjang dulu; word boundary biar 'Mar' tra kena 'mari'
    for name in sorted(_all_keret_names(), key=len, reverse=True):
        pattern = r"\b" + re.escape(name.lower()) + r"\b"
        if re.search(pattern, q):
            return name
    return None


def keret_response_hint(keret: str) -> str:
    data = _load_biak()
    block = data.get("keret")
    if isinstance(block, dict):
        template = str(block.get("detection_response_template") or "")
        if template and "{keret}" in template:
            return template.format(keret=keret)
    return (
        f"Adooo anak Keret {keret} kah?! Syowi kaka! "
        "Kam dorang dari Biak sebelah mana dulu? Mari kitong baku bawa cerita sudah!"
    )


def retrieve_biak_facts(query: str | None, *, limit: int = _RETRIEVE_LIMIT) -> list[str]:
    if not query or not query.strip():
        return []
    data = _load_biak()
    out: list[str] = []

    detected = detect_keret(query)
    if detected:
        out.append(f"[Keret] Terdeteksi marga {detected} — {keret_response_hint(detected)[:120]}…")

    keret = data.get("keret")
    if isinstance(keret, dict):
        keywords = keret.get("keywords") or []
        if isinstance(keywords, list) and _score_keywords(query, [str(k) for k in keywords]) > 0:
            pop = keret.get("marga_populer") or []
            auwr = keret.get("marga_auwr_kuno") or []
            if isinstance(pop, list) and pop:
                out.append(f"[Keret populer] {', '.join(str(x) for x in pop[:6])}…")
            if isinstance(auwr, list) and auwr:
                out.append(f"[Keret Auwr kuno] {', '.join(str(x) for x in auwr[:6])}…")

    sub = data.get("sub_suku")
    if isinstance(sub, dict):
        keywords = sub.get("keywords") or []
        groups = sub.get("groups") or []
        if isinstance(keywords, list) and isinstance(groups, list):
            if _score_keywords(query, [str(k) for k in keywords]) > 0:
                fact = str(sub.get("fact") or "")
                out.append(f"[Sub-suku Biak] {', '.join(str(g) for g in groups)}. {fact}")

    wor = data.get("wor_tradition")
    if isinstance(wor, dict):
        keywords = wor.get("keywords") or []
        if isinstance(keywords, list) and _score_keywords(query, [str(k) for k in keywords]) > 0:
            overview = str(wor.get("overview") or "")
            if overview:
                out.append(f"[Wor] {overview}")
            variants = wor.get("variants")
            if isinstance(variants, list):
                for var in variants[:3]:
                    if not isinstance(var, dict):
                        continue
                    name = str(var.get("name") or "")
                    about = str(var.get("about") or "")
                    if name and about:
                        out.append(f"[Wor — {name}] {about}")

    mas = data.get("mas_kawin")
    if isinstance(mas, dict):
        keywords = mas.get("keywords") or []
        facts = mas.get("facts") or []
        if isinstance(keywords, list) and isinstance(facts, list):
            score = _score_keywords(query, [str(k) for k in keywords])
            if score > 0:
                title = str(mas.get("title") or "Mas Kawin Biak")
                for fact in facts[:3]:
                    line = f"[{title}] {fact}"
                    if len(line) > _CHAR_LIMIT:
                        line = line[: _CHAR_LIMIT - 1] + "…"
                    out.append(line)
                dialog = str(mas.get("dialog_template") or "")
                if dialog and score >= 2:
                    out.append(f"[Ararem dialog] {dialog[:140]}…" if len(dialog) > 140 else f"[Ararem dialog] {dialog}")

    coastal = data.get("coastal_phrases")
    if isinstance(coastal, list):
        for entry in coastal:
            if not isinstance(entry, dict):
                continue
            kws = entry.get("keywords") or []
            if not isinstance(kws, list):
                continue
            if _score_keywords(query, [str(k) for k in kws]) > 0:
                phrase = str(entry.get("phrase") or "")
                meaning = str(entry.get("meaning") or "")
                if phrase and meaning:
                    out.append(f"[Pesisir Biak] {phrase} = {meaning}")

    vocab = data.get("vocabulary")
    if isinstance(vocab, list):
        ranked: list[tuple[int, dict]] = []
        for entry in vocab:
            if not isinstance(entry, dict):
                continue
            kws = entry.get("keywords") or []
            if not isinstance(kws, list):
                continue
            score = _score_keywords(query, [str(k) for k in kws])
            if score > 0:
                ranked.append((score, entry))
        ranked.sort(key=lambda x: x[0], reverse=True)
        for _score, entry in ranked[:2]:
            biak = str(entry.get("biak") or "")
            meaning = str(entry.get("meaning") or "")
            if biak and meaning:
                out.append(f"[Wós Vyak] {biak} = {meaning}")

    songs = data.get("songs")
    if isinstance(songs, list):
        ranked_s: list[tuple[int, dict]] = []
        for song in songs:
            if not isinstance(song, dict):
                continue
            kws = song.get("keywords") or []
            if not isinstance(kws, list):
                continue
            score = _score_keywords(query, [str(k) for k in kws])
            if score > 0:
                ranked_s.append((score, song))
        ranked_s.sort(key=lambda x: x[0], reverse=True)
        for _score, song in ranked_s[:2]:
            title = str(song.get("title") or "Lagu Biak")
            about = str(song.get("about") or "")
            line = f"[Lagu Biak] {title} — {about}" if about else f"[Lagu Biak] {title}"
            if len(line) > _CHAR_LIMIT:
                line = line[: _CHAR_LIMIT - 1] + "…"
            out.append(line)

    return out[:limit]


def _biak_query(query: str | None) -> bool:
    if not query:
        return False
    if detect_keret(query):
        return True
    q = _normalize(query)
    triggers = (
        "biak", "byak", "wos vyak", "wós vyak", "ararem", "farkawawin", "piring gantung",
        "benjaf", "sner", "syowi", "kopyum", "imboi", "wondama", "diru diru",
        "musik wor", "maskawin", "mas kawin", "keret", "marga", "kabor", "akur",
        "mambri", "ersam", "korfandi", "dow bekok", "sub suku", "aimando", "doreri",
    )
    return any(t in q for t in triggers)


def biak_prompt_lines(
    dialect: str | None,
    *,
    language: str = "id",
    query: str | None = None,
    include_overview: bool = True,
) -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []

    data = _load_biak()
    if not data:
        return []

    lines = [
        f"Suku Biak / Orang Byak ({vocabulary_count()} Wós Vyak, {keret_count()} keret/marga):",
        f"- {usage_note()}",
        "- DETEKSI KERET: kalau user sebut marga di nama (mis. Rumbiak, Rumansara) — tanggap personal: Syowi + tanya asal Biak + hangat.",
        "- Ararem: Benjaf (Piring Gantung) + Sner (Guci) + uang susu; tra bawa piring = tra lepas kain gendong.",
        "- Wor samudra (korfandi): Ersam, Dow Be Kok Masan, Dow Bekok Wam — pelaut Biak ke Raja Ampat & Filipina.",
        "- Frasa pesisir: Kabor!, Akur!, Mambri, Ado bapak ee…",
    ]

    if include_overview:
        keret = data.get("keret")
        if isinstance(keret, dict):
            pop = keret.get("marga_populer") or []
            if isinstance(pop, list) and pop:
                sample = ", ".join(str(x) for x in pop[:_PROMPT_KERET_LIMIT])
                lines.append(f"- Keret populer: {sample}…")
            sub = data.get("sub_suku")
            if isinstance(sub, dict):
                groups = sub.get("groups") or []
                if isinstance(groups, list) and groups:
                    lines.append(f"- Sub-suku: {', '.join(str(g) for g in groups)}")

        vocab = data.get("vocabulary")
        if isinstance(vocab, list):
            lines.append("- Contoh Wós Vyak:")
            for entry in vocab[:_PROMPT_VOCAB_LIMIT]:
                if not isinstance(entry, dict):
                    continue
                biak = str(entry.get("biak") or "")
                meaning = str(entry.get("meaning") or "")
                if biak and meaning:
                    lines.append(f"  · {biak} = {meaning}")

    if query:
        detected = detect_keret(query)
        if detected:
            lines.append(f"- MARGA TERDETEKSI ({detected}): {keret_response_hint(detected)}")

    if query and (_biak_query(query) or retrieve_biak_facts(query, limit=1)):
        hits = retrieve_biak_facts(query)
        if hits:
            lines.append("- Relevan obrolan ko sekarang:")
            lines.extend(f"  · {h}" for h in hits[:5])

    return lines
