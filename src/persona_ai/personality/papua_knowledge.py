"""Knowledge base Papua — fakta untuk asisten suara (keyword retrieval)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

_DATA_PATH = Path(__file__).parent / "data" / "papua_knowledge.json"

_CORE_LIMIT = 8
_RETRIEVE_TOPIC_LIMIT = 3
_RETRIEVE_FACTS_PER_TOPIC = 2
_PROMPT_FACT_CHAR_LIMIT = 140


@lru_cache(maxsize=1)
def _load_kb() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _score_topic(query: str, keywords: list[str]) -> int:
    q = _normalize(query)
    score = 0
    for kw in keywords:
        kw = kw.lower().strip()
        if not kw:
            continue
        if kw in q:
            score += 2 if " " in kw else 1
    return score


def core_knowledge_facts() -> list[str]:
    data = _load_kb()
    facts = data.get("core_facts")
    if not isinstance(facts, list):
        return []
    return [str(f).strip() for f in facts if str(f).strip()][: _CORE_LIMIT]


def retrieve_knowledge_facts(query: str | None, *, limit: int = 5) -> list[str]:
    """Ambil fakta relevan dari topik KB berdasarkan kata kunci di query user."""
    if not query or not query.strip():
        return []
    data = _load_kb()
    topics = data.get("topics")
    if not isinstance(topics, list):
        return []

    ranked: list[tuple[int, str, list[str]]] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        keywords = topic.get("keywords")
        facts = topic.get("facts")
        if not isinstance(keywords, list) or not isinstance(facts, list):
            continue
        score = _score_topic(query, [str(k) for k in keywords])
        if score <= 0:
            continue
        title = str(topic.get("title") or topic.get("id") or "Papua")
        clean_facts = [str(f).strip() for f in facts if str(f).strip()]
        ranked.append((score, title, clean_facts))

    ranked.sort(key=lambda item: item[0], reverse=True)
    out: list[str] = []
    for _score, title, facts in ranked[:_RETRIEVE_TOPIC_LIMIT]:
        for fact in facts[:_RETRIEVE_FACTS_PER_TOPIC]:
            line = f"[{title}] {fact}"
            if len(line) > _PROMPT_FACT_CHAR_LIMIT:
                line = line[: _PROMPT_FACT_CHAR_LIMIT - 1] + "…"
            if line not in out:
                out.append(line)
            if len(out) >= limit:
                return out
    return out


def knowledge_usage_note() -> str:
    data = _load_kb()
    note = data.get("usage_note")
    return str(note).strip() if note else "Pakai fakta Papua di bawah; kalau tra tau, bilang jujur."


def knowledge_prompt_lines(
    dialect: str | None,
    *,
    language: str = "id",
    query: str | None = None,
    include_core: bool = True,
) -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []

    lines = [
        "Pengetahuan Papua (knowledge base — pakai saat ko tanya tentang Papua):",
        f"- {knowledge_usage_note()}",
    ]

    if include_core:
        core = core_knowledge_facts()
        if core:
            lines.append("- Fakta inti:")
            lines.extend(f"  · {fact}" for fact in core)

    retrieved = retrieve_knowledge_facts(query)
    if retrieved:
        lines.append("- Relevan dengan obrolan ko sekarang:")
        lines.extend(f"  · {fact}" for fact in retrieved)

    return lines


def topic_count() -> int:
    data = _load_kb()
    topics = data.get("topics")
    return len(topics) if isinstance(topics, list) else 0
