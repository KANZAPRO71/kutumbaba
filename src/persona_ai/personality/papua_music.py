"""Katalog lagu & musik Papua — retrieval untuk teman ngobrol suara."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

_DATA_PATH = Path(__file__).parent / "data" / "papua_music.json"

_OVERVIEW_LIMIT = 5
_RETRIEVE_TOPIC_LIMIT = 3
_RETRIEVE_SONG_LIMIT = 5
_RETRIEVE_FACTS_PER_TOPIC = 2
_PROMPT_CHAR_LIMIT = 200

_MUSIC_QUERY_KEYWORDS = frozenset({
    "lagu", "lagu-lagu", "nyanyi", "nyanyian", "musik", "song", "songs", "music",
    "artis", "penyanyi", "band", "album", "lirik", "cover", "gospel", "rohani",
    "tifa", "yospan", "sosang", "apuse", "yamko", "franky", "abe pahabol",
    "edhy b", "nowela", "mambes", "charly", "onde-onde", "festival musik",
    "shine of black", "sob", "mac", "m.a.c", "jang ganggu", "cuma saya",
    "whllyano", "lean slim", "kapthenpurek", "silet open up", "yance rumbino",
    "tanah papua", "angkot", "nongkrong", "viral", "hip hop", "rap papua",
    "ko menang banyak", "kaka main salah", "turun naik",
})


@lru_cache(maxsize=1)
def _load_catalog() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def usage_note() -> str:
    data = _load_catalog()
    note = data.get("usage_note")
    return str(note).strip() if note else "Pakai katalog musik Papua; kalau tra yakin, bilang jujur."


def overview_lines() -> list[str]:
    data = _load_catalog()
    items = data.get("overview")
    if not isinstance(items, list):
        return []
    return [str(i).strip() for i in items if str(i).strip()][: _OVERVIEW_LIMIT]


def song_count() -> int:
    data = _load_catalog()
    songs = data.get("songs")
    return len(songs) if isinstance(songs, list) else 0


def topic_count() -> int:
    data = _load_catalog()
    topics = data.get("topics")
    return len(topics) if isinstance(topics, list) else 0


def catalog_count() -> int:
    return song_count() + topic_count()


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


def _music_query(query: str | None) -> bool:
    if not query or not query.strip():
        return False
    q = _normalize(query)
    return any(kw in q for kw in _MUSIC_QUERY_KEYWORDS)


def retrieve_music_facts(query: str | None, *, limit: int = 6) -> list[str]:
    if not query or not query.strip():
        return []
    data = _load_catalog()
    q = _normalize(query)
    music = _music_query(query)
    ranked: list[tuple[int, str]] = []

    topics = data.get("topics")
    if isinstance(topics, list):
        for topic in topics:
            if not isinstance(topic, dict):
                continue
            keywords = [str(k) for k in (topic.get("keywords") or [])]
            facts = topic.get("facts")
            if not isinstance(facts, list):
                continue
            score = _score_keywords(q, keywords)
            if score <= 0 and not music:
                continue
            title = str(topic.get("title") or topic.get("id") or "Musik Papua")
            for fact in facts[:_RETRIEVE_FACTS_PER_TOPIC]:
                text = str(fact).strip()
                if text:
                    line = f"[{title}] {text}"
                    if len(line) > _PROMPT_CHAR_LIMIT:
                        line = line[: _PROMPT_CHAR_LIMIT - 1] + "…"
                    ranked.append((score + (1 if music else 0), line))

    songs = data.get("songs")
    if isinstance(songs, list):
        for song in songs:
            if not isinstance(song, dict):
                continue
            title = str(song.get("title") or "").strip()
            about = str(song.get("about") or "").strip()
            if not title or not about:
                continue
            artists = song.get("artists")
            artist_str = ""
            if isinstance(artists, list) and artists:
                artist_str = " — " + ", ".join(str(a) for a in artists[:3])
            keywords = [str(k) for k in (song.get("keywords") or [])]
            if title.lower() not in keywords:
                keywords.append(title.lower())
            score = _score_keywords(q, keywords)
            genre = str(song.get("genre") or "").strip()
            region = str(song.get("region") or "").strip()
            meta = " · ".join(x for x in (genre, region) if x)
            line = f"「{title}」{artist_str}"
            if meta:
                line += f" ({meta})"
            line += f": {about}"
            hint = str(song.get("lyrics_hint") or "").strip()
            if hint and (score > 0 or music):
                line += f" | Lirik/tema: {hint[:80]}"
            if len(line) > _PROMPT_CHAR_LIMIT:
                line = line[: _PROMPT_CHAR_LIMIT - 1] + "…"
            if score > 0 or music:
                ranked.append((score + (3 if music else 0), line))

    ranked.sort(key=lambda x: x[0], reverse=True)
    out: list[str] = []
    for _score, line in ranked:
        if line not in out:
            out.append(line)
        if len(out) >= limit:
            break

    if music and len(out) < 2:
        for line in overview_lines()[:2]:
            if line not in out:
                out.append(line)
    return out


def preview_songs(limit: int = 6) -> list[str]:
    data = _load_catalog()
    songs = data.get("songs")
    if not isinstance(songs, list):
        return []
    out: list[str] = []
    for song in songs:
        if not isinstance(song, dict):
            continue
        title = str(song.get("title") or "").strip()
        if not title:
            continue
        artists = song.get("artists")
        if isinstance(artists, list) and artists:
            out.append(f"{title} — {artists[0]}")
        else:
            out.append(title)
        if len(out) >= limit:
            break
    return out


def music_prompt_lines(
    dialect: str | None,
    *,
    language: str = "id",
    query: str | None = None,
    include_overview: bool = True,
) -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []

    total_songs = song_count()
    total_topics = topic_count()
    lines = [
        f"Katalog musik & lagu Papua ({total_songs} lagu + {total_topics} topik — ko harus kuasai):",
        f"- {usage_note()}",
        "- Kalau ko tanya lagu/musik Papua: sebut judul, artis, genre, nuansa; bandingkan kalau perlu (Apuse vs gospel vs Yospan).",
        "- Legenda wajib ingat: Apuse, Hai Tanahku Papua, Yamko Rambe Yamko, Franky Sahilatua & Abe Pahabol.",
        "- Adat: tifa, Yospan/Sosang, Onde-Onde Sentani; modern: Edhy B, Nowela, Mambes, gospel gereja.",
    ]

    if include_overview:
        overview = overview_lines()
        if overview:
            lines.append("- Gambaran umum musik Papua:")
            lines.extend(f"  · {o}" for o in overview)

    if query and (_music_query(query) or retrieve_music_facts(query, limit=1)):
        retrieved = retrieve_music_facts(query)
        if retrieved:
            lines.append("- Relevan dengan obrolan ko sekarang:")
            lines.extend(f"  · {r}" for r in retrieved)
    elif include_overview:
        samples = preview_songs(4)
        if samples:
            lines.append("- Contoh lagu terkenal:")
            lines.extend(f"  · {s}" for s in samples)

    return lines
