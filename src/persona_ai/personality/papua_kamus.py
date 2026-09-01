"""Kamus Bahasa Papua — lookup & retrieval untuk teman ngobrol suara."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

_DATA_PATH = Path(__file__).parent / "data" / "papua_kamus.json"

_RETRIEVE_LIMIT = 8
_PREVIEW_LIMIT = 8
_PROMPT_CHAR_LIMIT = 160

_KAMUS_QUERY_KEYWORDS = frozenset({
    "kamus", "arti", "maksud", "terjemah", "terjemahan", "bahasa papua",
    "kata papua", "apa arti", "artinya", "makna", "vocabul", "kosakata",
    "istilah papua", "dialek", "logat", "melayu papua",
})


@lru_cache(maxsize=1)
def _load_kamus() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=1)
def _entries() -> tuple[dict, ...]:
    data = _load_kamus()
    items = data.get("entries")
    if not isinstance(items, list):
        return ()
    out: list[dict] = []
    for item in items:
        if isinstance(item, dict) and str(item.get("word", "")).strip():
            out.append(item)
    return tuple(out)


@lru_cache(maxsize=1)
def _word_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for item in _entries():
        word = str(item.get("word", "")).strip()
        if word:
            index[word.lower()] = item
    return index


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def usage_note() -> str:
    data = _load_kamus()
    note = data.get("usage_note")
    return str(note).strip() if note else "Pakai kamus Papua; kalau tra yakin, bilang jujur."


def entry_count() -> int:
    return len(_entries())


def lookup_word(word: str | None) -> dict | None:
    if not word or not word.strip():
        return None
    return _word_index().get(word.strip().lower())


def preview_entries(limit: int = _PREVIEW_LIMIT) -> list[str]:
    previews: list[str] = []
    prefer = (
        "sa", "ko", "pi", "tra", "su", "mo", "pu", "mamayo", "bale", "mangarti",
        "trapapa", "kapala batu", "abuti", "tafiaro", "pace", "maitua",
    )
    index = _word_index()
    for key in prefer:
        item = index.get(key)
        if not item:
            continue
        word = str(item.get("word", ""))
        meaning = str(item.get("meaning", ""))
        line = f"{word} = {meaning}"
        if line not in previews:
            previews.append(line[:120])
        if len(previews) >= limit:
            return previews
    for item in _entries():
        if len(previews) >= limit:
            break
        word = str(item.get("word", ""))
        meaning = str(item.get("meaning", ""))
        line = f"{word} = {meaning}"
        if line not in previews:
            previews.append(line[:120])
    return previews


def _score_keywords(query: str, keywords: list[str]) -> int:
    q = _normalize(query)
    score = 0
    for kw in keywords:
        kw = kw.lower().strip()
        if not kw:
            continue
        if kw in q:
            score += 3 if " " in kw else 2
    return score


def _kamus_query(query: str | None) -> bool:
    if not query or not query.strip():
        return False
    q = _normalize(query)
    return any(kw in q for kw in _KAMUS_QUERY_KEYWORDS)


def _tokens_in_query(query: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9'-]+", _normalize(query)) if len(t) >= 2]


def retrieve_kamus(query: str | None, *, limit: int = _RETRIEVE_LIMIT) -> list[str]:
    if not query or not query.strip():
        return []
    q = _normalize(query)
    kamus = _kamus_query(query)
    ranked: list[tuple[int, str]] = []

    for token in _tokens_in_query(query):
        hit = lookup_word(token)
        if hit:
            word = str(hit.get("word", ""))
            meaning = str(hit.get("meaning", ""))
            line = f"{word} = {meaning}"
            ranked.append((10, line[:_PROMPT_CHAR_LIMIT]))

    for item in _entries():
        word = str(item.get("word", "")).strip()
        meaning = str(item.get("meaning", "")).strip()
        if not word or not meaning:
            continue
        keywords = [str(k) for k in (item.get("keywords") or [])]
        if word.lower() not in keywords:
            keywords.append(word.lower())
        score = _score_keywords(q, keywords)
        if word.lower() in q:
            score += 4
        if score > 0:
            line = f"{word} = {meaning}"
            if len(line) > _PROMPT_CHAR_LIMIT:
                line = line[: _PROMPT_CHAR_LIMIT - 1] + "…"
            ranked.append((score, line))

    ranked.sort(key=lambda x: x[0], reverse=True)
    out: list[str] = []
    for _score, line in ranked:
        if line not in out:
            out.append(line)
        if len(out) >= limit:
            break

    if kamus and not out:
        out.extend(preview_entries(min(4, limit)))
    return out


def kamus_prompt_lines(
    dialect: str | None,
    *,
    language: str = "id",
    query: str | None = None,
    include_overview: bool = True,
) -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []

    total = entry_count()
    lines = [
        f"Kamus Bahasa Papua ({total} kata — percakapan sehari-hari, lintas suku):",
        f"- {usage_note()}",
        "- Kalau ko tanya arti kata: jawab jelas (Papua → Indonesia), sebut kalau kata Biak/suku spesifik.",
        "- Seling kosakata natural saat ngobrol — jangan jadi kamus berjalan tiap kalimat.",
    ]

    if include_overview:
        previews = preview_entries(6)
        if previews:
            lines.append("- Contoh kata umum:")
            lines.extend(f"  · {p}" for p in previews)

    if query and (_kamus_query(query) or retrieve_kamus(query, limit=1)):
        hits = retrieve_kamus(query)
        if hits:
            lines.append("- Relevan dengan obrolan ko sekarang:")
            lines.extend(f"  · {h}" for h in hits)

    return lines
