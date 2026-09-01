"""STT tuning — kosakata & slang Melayu Papua untuk Gemini Live ASR."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect
from persona_ai.web.voice_config import LiveVoiceConfig, PronunciationGuide

_DATA_PATH = Path(__file__).parent / "data" / "papua_stt_lexicon.json"

_ASR_PROMPT_LIMIT = 12
_SLANG_PROMPT_LIMIT = 8
_MAPPING_PROMPT_LIMIT = 10

_WORD_BOUNDARY = r"(?<![a-z0-9]){}(?![a-z0-9])"


@lru_cache(maxsize=1)
def _load_lexicon() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def boosted_keywords() -> tuple[str, ...]:
    data = _load_lexicon()
    raw = data.get("boosted_keywords")
    if not isinstance(raw, list):
        return ()
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        word = str(item).strip()
        key = word.lower()
        if word and key not in seen:
            seen.add(key)
            out.append(word)
    return tuple(out)


def phonetic_entries() -> list[dict]:
    data = _load_lexicon()
    items = data.get("phonetic_entries")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def slang_aliases() -> list[dict]:
    data = _load_lexicon()
    items = data.get("slang_aliases")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def contextual_mappings() -> list[dict]:
    data = _load_lexicon()
    items = data.get("contextual_mappings")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def normalize_papua_transcript(text: str | None, *, dialect: str | None = "papua") -> str:
    """Perbaiki teks STT yang salah dengar logat Melayu Papua."""
    if not text or not str(text).strip():
        return ""
    if not is_papua_dialect(dialect):
        return text.strip()

    normalized = text.strip()
    lower = normalized.lower()

    for mapping in contextual_mappings():
        correct = str(mapping.get("correct", "")).strip()
        errors = mapping.get("stt_errors")
        if not correct or not isinstance(errors, list):
            continue
        for err in errors:
            err = str(err).strip().lower()
            if not err or err == correct.lower():
                continue
            if " " in err:
                pattern = re.compile(re.escape(err), re.IGNORECASE)
            else:
                pattern = re.compile(_WORD_BOUNDARY.format(re.escape(err)), re.IGNORECASE)
            normalized = pattern.sub(correct, normalized)

    for alias in slang_aliases():
        a = str(alias.get("alias", "")).strip()
        w = str(alias.get("word", "")).strip()
        if not a or not w:
            continue
        pattern = re.compile(_WORD_BOUNDARY.format(re.escape(a)), re.IGNORECASE)
        normalized = pattern.sub(w, normalized)

    return re.sub(r"\s+", " ", normalized).strip()


def mapping_prompt_lines(dialect: str | None, *, language: str = "id") -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []
    lines = ["Pemetaan kosakata kontekstual (STT user -> arti Papua):"]
    for mapping in contextual_mappings()[:_MAPPING_PROMPT_LIMIT]:
        correct = str(mapping.get("correct", ""))
        meaning = str(mapping.get("meaning", ""))
        errors = mapping.get("stt_errors")
        err_text = ""
        if isinstance(errors, list) and errors:
            err_text = f" (STT salah: {', '.join(str(e) for e in errors[:3])})"
        if correct:
            lines.append(f"  · {correct} = {meaning}{err_text}")
    return lines


def asr_context_hints() -> list[str]:
    data = _load_lexicon()
    hints = data.get("asr_context_hints")
    if not isinstance(hints, list):
        return []
    return [str(h).strip() for h in hints if str(h).strip()]


def _pronunciation_guides() -> tuple[PronunciationGuide, ...]:
    guides: list[PronunciationGuide] = []
    for entry in phonetic_entries():
        word = str(entry.get("word", "")).strip()
        meaning = str(entry.get("meaning", "")).strip()
        avoid = entry.get("avoid_as")
        if not word:
            continue
        avoid_text = ""
        if isinstance(avoid, list) and avoid:
            avoid_text = f" — jangan dibaca sebagai {', '.join(str(a) for a in avoid[:3])}"
        guides.append(PronunciationGuide(word=word, guide=f"Melayu Papua: {meaning}{avoid_text}"))
    for alias in slang_aliases()[:6]:
        a = str(alias.get("alias", "")).strip()
        w = str(alias.get("word", "")).strip()
        m = str(alias.get("meaning", "")).strip()
        if a and w:
            guides.append(PronunciationGuide(word=a, guide=f"singkatan chat → {w} ({m})"))
    return tuple(guides)


def enrich_voice_config_for_papua(voice: LiveVoiceConfig) -> LiveVoiceConfig:
    """Gabungkan kamus STT Papua ke boosted_keywords & pronunciations."""
    papua_kw = boosted_keywords()
    if not papua_kw:
        return voice
    merged_kw: list[str] = []
    seen: set[str] = set()
    for word in (*voice.boosted_keywords, *papua_kw):
        key = word.lower()
        if key not in seen:
            seen.add(key)
            merged_kw.append(word)
    existing_words = {p.word.lower() for p in voice.pronunciations}
    extra_pron = [p for p in _pronunciation_guides() if p.word.lower() not in existing_words]
    return replace(
        voice,
        boosted_keywords=tuple(merged_kw),
        pronunciations=voice.pronunciations + tuple(extra_pron),
    )


def stt_prompt_lines(dialect: str | None, *, language: str = "id") -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []
    lines = [
        "STT / transkrip user — Melayu Papua (jangan salah artikan):",
        "- User pakai sa/ko/tra/su/mo/pu/kitong/kam/dorang — itu kosakata Papua, bukan typo.",
    ]
    for hint in asr_context_hints()[:4]:
        lines.append(f"- {hint}")
    lines.append("- Kamus fonetik (tra≠tren/truk, su=sudah, pace=laki-laki, mace=ibu):")
    for entry in phonetic_entries()[:_ASR_PROMPT_LIMIT]:
        word = str(entry.get("word", ""))
        meaning = str(entry.get("meaning", ""))
        avoid = entry.get("avoid_as")
        avoid_note = ""
        if isinstance(avoid, list) and avoid:
            avoid_note = f" (bukan {avoid[0]})"
        if word and meaning:
            lines.append(f"  · {word} = {meaning}{avoid_note}")
    lines.append("- Slang/singkatan chat (artikan otomatis):")
    for alias in slang_aliases()[:_SLANG_PROMPT_LIMIT]:
        a = str(alias.get("alias", ""))
        w = str(alias.get("word", ""))
        m = str(alias.get("meaning", ""))
        if a and w:
            lines.append(f"  · {a} → {w} ({m})")
    lines.extend(mapping_prompt_lines(dialect, language=language))
    return lines
