"""Master System Instruction — otak Papua AI untuk Gemini Live (siap pakai)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

_DATA_PATH = Path(__file__).parent / "data" / "papua_live_system_instruction.json"


@lru_cache(maxsize=1)
def _load_master() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _section_lines(section: dict | None) -> list[str]:
    if not isinstance(section, dict):
        return []
    title = str(section.get("title", "")).strip()
    items = section.get("lines")
    if not isinstance(items, list):
        return []
    lines: list[str] = []
    if title:
        lines.append(f"{title}:")
    for item in items:
        text = str(item).strip()
        if text:
            lines.append(f"- {text}")
    return lines


def master_system_instruction_lines(
    dialect: str | None,
    *,
    language: str = "id",
    display_name: str = "Papua AI",
) -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []
    data = _load_master()
    sections = data.get("sections")
    if not isinstance(sections, dict):
        return []

    name = display_name or str(data.get("display_name_default") or "Papua AI")
    lines = [
        f"=== PAPUA AI — MASTER SYSTEM INSTRUCTION ({name}) ===",
        "Ikuti blok ini sebagai konstitusi suara — natural, bukan baca bullet.",
    ]

    order = (
        "role_identity",
        "developer_credit",
        "raja_mop",
        "tone_language",
        "mop_humor",
        "knowledge_priorities",
        "vowel_prosody",
        "full_duplex",
        "ondo_wibawa",
        "gaul_trendsetter",
    )
    for key in order:
        block = _section_lines(sections.get(key))
        if block:
            lines.append("")
            lines.extend(block)

    return lines


def master_system_instruction_text(
    dialect: str | None,
    *,
    language: str = "id",
    display_name: str = "Papua AI",
) -> str:
    """Teks utuh siap copy-paste ke Gemini Live systemInstruction."""
    lines = master_system_instruction_lines(
        dialect, language=language, display_name=display_name
    )
    if not lines:
        return ""
    return "\n".join(lines)
