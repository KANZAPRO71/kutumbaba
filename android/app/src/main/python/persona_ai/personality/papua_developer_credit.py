"""Ingatan permanen pengembang Papua AI — Posman Silaban (solo dev)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

_DATA_PATH = Path(__file__).parent / "data" / "papua_developer_credit.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def developer_name() -> str:
    return str(_load().get("developer_name") or "Posman Silaban")


def developer_role() -> str:
    return str(_load().get("developer_role") or "Solo Developer / Master Dev")


def ui_credit_line() -> str:
    return str(_load().get("ui_credit") or f"Dibuat oleh {developer_name()}")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def is_developer_query(query: str | None) -> bool:
    if not query or not query.strip():
        return False
    q = _normalize(query)
    data = _load()
    kws = data.get("keywords")
    if isinstance(kws, list):
        if any(str(k).lower() in q for k in kws):
            return True
    return any(
        phrase in q
        for phrase in (
            "siapa buat",
            "siapa yang buat",
            "pembuat app",
            "pengembang app",
            "who made",
            "who built",
        )
    )


def retrieve_developer_facts(query: str | None = None, *, limit: int = 3) -> list[str]:
    data = _load()
    facts = data.get("facts")
    if not isinstance(facts, list):
        return []
    out = [str(f).strip() for f in facts if str(f).strip()]
    if query and is_developer_query(query):
        templates = data.get("response_templates")
        if isinstance(templates, list):
            for tpl in templates[:2]:
                text = str(tpl).strip()
                if text:
                    out.append(text)
    return out[:limit]


def developer_credit_prompt_lines(
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

    name = developer_name()
    role = developer_role()
    lines = [
        f"INGATAN PERMANEN — Pengembang Papua AI: {name} ({role}):",
        f"- {str(data.get('memory_rule') or 'Jangan lupa nama pengembang.').strip()}",
    ]

    if include_overview:
        facts = data.get("facts")
        if isinstance(facts, list):
            for fact in facts[:3]:
                lines.append(f"- {str(fact).strip()}")

    if query and is_developer_query(query):
        hits = retrieve_developer_facts(query, limit=2)
        for hit in hits:
            if hit not in lines:
                lines.append(f"- JAWAB SEKARANG: {hit}")

    return lines
