"""Koleksi Mop Papua — lelucon verbal Melayu Papua untuk teman ngobrol suara."""

from __future__ import annotations

import json
import random
import re
from collections import deque
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect
from persona_ai.personality.papua_mop_intros import (
    mop_intro_prompt_lines,
    punchline_pause_prompt_lines,
)
from persona_ai.personality.papua_mop_landmarks import landmark_prompt_lines

_DATA_PATH = Path(__file__).parent / "data" / "papua_mops.json"

_SESSION_SAMPLE_LIMIT = 12
_RETRIEVE_LIMIT = 8
_PREVIEW_LIMIT = 8
_PROMPT_CHAR_LIMIT = 220
_RANDOM_MOP_MEMORY = 5

_FALLBACK_RANDOM_MOP = (
    "Adoo kawan, sa pung ingatan lagi penuh, tunggu sa ingat-ingat dulu ee!"
)

_recent_mop_keys: deque[str] = deque(maxlen=_RANDOM_MOP_MEMORY)

_HUMOR_QUERY_KEYWORDS = frozenset({
    "mop", "mob", "lucu", "ketawa", "lawak", "lelucon", "humor", "ngakak",
    "epen", "cupen", "mamayo", "eee", "jeskon", "yoksna", "istigafar",
    "cerita lucu", "bikin ketawa", "menipu orang banyak",
    "ceritain", "cerita mop", "cerita mob", "bikin sa ketawa",
    "kasi mop", "mop dulu", "kasih mop", "ceritain mop",
})


@lru_cache(maxsize=1)
def _load_mops() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _category_items() -> list[tuple[str, list[str], list[str]]]:
    """(category_id, keywords, phrase texts)"""
    data = _load_mops()
    out: list[tuple[str, list[str], list[str]]] = []
    categories = data.get("categories")
    if not isinstance(categories, list):
        return out
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        cat_id = str(cat.get("id") or "mop")
        keywords = [str(k).lower() for k in (cat.get("keywords") or []) if str(k).strip()]
        items = cat.get("items")
        if not isinstance(items, list):
            continue
        texts = [str(i).strip() for i in items if str(i).strip()]
        if texts:
            out.append((cat_id, keywords, texts))
    return out


def _all_classic_mops() -> list[dict]:
    data = _load_mops()
    items = data.get("classic_mops")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and str(item.get("text", "")).strip()]


def _all_short_mops() -> list[dict]:
    data = _load_mops()
    items = data.get("short_mops")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and str(item.get("text", "")).strip()]


def mop_count() -> int:
    total = sum(len(texts) for _cid, _kw, texts in _category_items())
    return total + len(_all_short_mops()) + len(_all_classic_mops())


def classic_mop_count() -> int:
    return len(_all_classic_mops())


def usage_note() -> str:
    data = _load_mops()
    note = data.get("usage_note")
    return str(note).strip() if note else "Mop = lelucon Melayu Papua — pakai secukupnya kalau pas."


def session_mop_samples() -> list[str]:
    """Sampel bervariasi untuk instruksi sesi — round-robin antar kategori + cerita pendek."""
    samples: list[str] = []
    by_cat = {cat_id: texts for cat_id, _kw, texts in _category_items()}
    cat_ids = list(by_cat.keys())
    idx = 0
    while len(samples) < _SESSION_SAMPLE_LIMIT and cat_ids:
        cat_id = cat_ids[idx % len(cat_ids)]
        texts = by_cat[cat_id]
        pick = texts[(idx // len(cat_ids)) % len(texts)]
        if pick not in samples:
            samples.append(pick)
        idx += 1
        if idx > _SESSION_SAMPLE_LIMIT * max(len(cat_ids), 1) * 2:
            break

    for short in _all_short_mops():
        if len(samples) >= _SESSION_SAMPLE_LIMIT:
            break
        text = str(short.get("text", "")).strip()
        if text and text not in samples:
            samples.append(text[:_PROMPT_CHAR_LIMIT])

    return samples[:_SESSION_SAMPLE_LIMIT]


def preview_mops(limit: int = _PREVIEW_LIMIT) -> list[str]:
    previews: list[str] = []
    for _cat_id, _kw, texts in _category_items():
        for text in texts:
            if text not in previews:
                previews.append(text)
            if len(previews) >= limit:
                return previews
    for short in _all_short_mops():
        if len(previews) >= limit:
            break
        text = str(short.get("text", "")).strip()
        if text and text not in previews:
            previews.append(text[:120] + ("…" if len(text) > 120 else ""))
    return previews[:limit]


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


def _humor_query(query: str | None) -> bool:
    if not query or not query.strip():
        return False
    q = _normalize(query)
    return any(kw in q for kw in _HUMOR_QUERY_KEYWORDS)


def pick_classic_mop() -> str | None:
    """Acak satu Mop klasik (Raja Mop — hindari ulang terakhir)."""
    return pick_random_mop(classics_only=True)


def _mop_pool(*, classics_only: bool = False) -> list[tuple[str, str]]:
    pool: list[tuple[str, str]] = []
    for item in _all_classic_mops():
        key = str(item.get("id") or item.get("title") or item.get("text", "")[:48])
        text = str(item.get("text", "")).strip()
        if text:
            pool.append((key, text))
    if classics_only:
        return pool
    try:
        from persona_ai.personality.papua_local_database import load_papua_database

        for index, text in enumerate(load_papua_database().get("mop_list") or []):
            cleaned = str(text).strip()
            if cleaned:
                pool.append((f"local_{index}", cleaned))
    except Exception:
        pass
    return pool


def pick_random_mop(*, classics_only: bool = False) -> str:
    """Raja Mop randomizer — acak dari klasik + database_papua.json, hindari ulang."""
    pool = _mop_pool(classics_only=classics_only)
    if not pool:
        return _FALLBACK_RANDOM_MOP

    available = [entry for entry in pool if entry[0] not in _recent_mop_keys]
    if not available:
        _recent_mop_keys.clear()
        available = pool

    key, text = random.choice(available)
    _recent_mop_keys.append(key)
    return text


def reset_random_mop_memory() -> None:
    """Kosongkan memori anti-ulang (tes / sesi baru)."""
    _recent_mop_keys.clear()


def retrieve_mops(query: str | None, *, limit: int = _RETRIEVE_LIMIT) -> list[str]:
    if not query or not query.strip():
        return []
    q = _normalize(query)
    humor = _humor_query(query)
    ranked: list[tuple[int, str]] = []

    for classic in _all_classic_mops():
        text = str(classic.get("text", "")).strip()
        if not text:
            continue
        title = str(classic.get("title") or "")
        keywords = [str(k) for k in (classic.get("keywords") or [])]
        score = _score_keywords(q, keywords)
        if "kasi mop" in q or "mop dulu" in q or "kasih mop" in q:
            score += 8
        if humor:
            score += 6
        if score > 0:
            line = text[:_PROMPT_CHAR_LIMIT]
            if title:
                line = f"[{title}] {line}"
            ranked.append((score, line))

    for short in _all_short_mops():
        text = str(short.get("text", "")).strip()
        if not text:
            continue
        keywords = [str(k) for k in (short.get("keywords") or [])]
        score = _score_keywords(q, keywords)
        if score > 0 or humor:
            ranked.append((score + (4 if humor else 0), text[:_PROMPT_CHAR_LIMIT]))

    for _cat_id, keywords, texts in _category_items():
        score = _score_keywords(q, keywords)
        for text in texts:
            item_score = score
            if any(w in q for w in text.lower().split()[:5] if len(w) > 3):
                item_score += 1
            if item_score > 0 or humor:
                ranked.append((item_score + (1 if humor else 0), text))

    ranked.sort(key=lambda x: x[0], reverse=True)
    out: list[str] = []
    for _score, text in ranked:
        if text not in out:
            out.append(text)
        if len(out) >= limit:
            break

    if humor and not out:
        random_mop = pick_random_mop()
        if random_mop:
            out.append(random_mop[:_PROMPT_CHAR_LIMIT])
        out.extend(session_mop_samples()[: max(0, limit - len(out))])
    return out


def mop_offer_prompt_lines() -> list[str]:
    """Instruksi tawarin Mop sesekali — nuansa Papua."""
    offers = mop_offer_phrases()[:5]
    offer_examples = " / ".join(f'"{p}"' for p in offers) if offers else '"Ko mo dengar sa pu Mop kah?"'
    return [
        "Penawaran Mop (sesekali — bukan tiap balasan):",
        f"- Kalau obrolan santai/light dan ko tra sedih/marah/serius, tawarin dulu: {offer_examples}",
        "- Frekuensi: kira-kira 1 kali setiap 4–8 giliran obrolan ringan, atau kalau obrolan agak sepi — jangan spam.",
        "- Kalau ko bilang iyo/mau/dengar — ceritakan 1 Mop pendek (1–3 kalimat suara), lalu diam dengar lagi.",
        "- Kalau ko tra/mo dulu/nanti saja — trapapa, lanjut obrolan biasa; jangan paksa.",
        "- Jangan tawarin Mop kalau ko lagi curhat berat, marah, minta bantuan serius, atau baru selesai cerita sedih.",
    ]


def mop_offer_phrases() -> list[str]:
    data = _load_mops()
    categories = data.get("categories")
    if isinstance(categories, list):
        for cat in categories:
            if isinstance(cat, dict) and cat.get("id") == "penawaran_mop":
                items = cat.get("items")
                if isinstance(items, list):
                    return [str(i).strip() for i in items if str(i).strip()]
    return [
        "Ko mo dengar sa pu Mop kah?",
        "Sa ada Mop lucu — ko mo dengar kah?",
        "Obrolan santai nih — ko mo dengar Mop dulu kah?",
        "Epen kah cupen toh — ko mo dengar sa pu Mop kah?",
    ]


def mop_prompt_lines(
    dialect: str | None,
    *,
    language: str = "id",
    query: str | None = None,
    include_session_samples: bool = True,
) -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []

    total = mop_count()
    lines = [
        f"Ko adalah Papua AI, Sang Raja Mop ({total} lelucon & reaksi — kuasai nuansa ini):",
        f"- {usage_note()}",
        "- Ko tangkis candaan cepat, sambung umpan mop pendek, jeda sebelum punchline — tawa singkat cuma di punchline, bukan di awal.",
        "- Ko punya bank Mop besar: reaksi (Mamayo, Macam apa eee), punchline, cerita pendek MBMP/EKCT, klasik MOP 1–21 (yombex, ondoafi, jordan, horor lucu).",
        "- Seling natural kalau obrolan santai/lucu; kalau ko minta mop/cerita lucu — ceritakan versi ringkas (1-3 kalimat suara).",
        "- Jangan paksa humor kalau ko sedih/serius; jangan jadi stand-up komedi tiap kalimat.",
        "- Ko bilang 'kasi mop' / 'mop dulu' — pilih intro BEDa + Mop ACAK, lalu ceritakan dengan ... sebelum punchline.",
        *mop_intro_prompt_lines(dialect, language=language),
        *punchline_pause_prompt_lines(dialect, language=language),
        *landmark_prompt_lines(dialect, language=language, query=query),
        *mop_offer_prompt_lines(),
    ]

    random_hint = pick_random_mop()
    if random_hint:
        lines.append(f"- Mop acak siap tembak sesi ini (jangan ulang terus): {random_hint[:180]}…")

    classics = _all_classic_mops()
    if classics:
        lines.append("- Mop klasik siap pakai (acak kalau ko minta):")
        for item in classics[:3]:
            title = str(item.get("title") or item.get("id") or "Mop")
            lines.append(f"  · {title}")

    if include_session_samples:
        samples = session_mop_samples()
        if samples:
            lines.append("- Contoh nuansa Mop (variasi, jangan dibaca persis):")
            lines.extend(f"  · {s}" for s in samples)

    if query:
        retrieved = retrieve_mops(query)
        if retrieved:
            lines.append("- Relevan dengan obrolan ko sekarang:")
            lines.extend(f"  · {m}" for m in retrieved)

    return lines
