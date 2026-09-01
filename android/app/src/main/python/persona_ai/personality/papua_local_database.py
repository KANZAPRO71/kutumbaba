"""Simple local RAG — load database_papua.json into Live system instruction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_DATABASE_FILENAME = "database_papua.json"

_SECTION_KEYS: tuple[tuple[str, str], ...] = (
    ("mop_list", "CERITA MOP KANTONG"),
    ("lagu_list", "DAFTAR LAGU POPULER"),
    ("budaya_list", "TRADISI BUDAYA"),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_database_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    script_sibling = _repo_root() / DEFAULT_DATABASE_FILENAME
    return script_sibling


def load_papua_database(path: Path | str | None = None) -> dict[str, list[str]]:
    """Read database_papua.json; return empty lists if file missing or invalid."""
    db_path = resolve_database_path(path)
    if not db_path.is_file():
        return {key: [] for key, _ in _SECTION_KEYS}

    try:
        raw: Any = json.loads(db_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {key: [] for key, _ in _SECTION_KEYS}

    if not isinstance(raw, dict):
        return {key: [] for key, _ in _SECTION_KEYS}

    out: dict[str, list[str]] = {}
    for key, _ in _SECTION_KEYS:
        items = raw.get(key, [])
        if not isinstance(items, list):
            items = []
        out[key] = [str(item).strip() for item in items if str(item).strip()]
    return out


def format_papua_database_context(data: dict[str, list[str]]) -> str:
    """Turn JSON sections into one instruction block for Gemini Live."""
    sections: list[str] = []
    for key, title in _SECTION_KEYS:
        items = data.get(key) or []
        if not items:
            continue
        sections.append(f"{title}:\n- " + "\n- ".join(items))

    if not sections:
        return ""

    return (
        "\n\nDATABASE PENGETAHUAN LOKALMU:\n"
        "Pakai data di bawah ini kalau user tanya mop, lagu, atau budaya Papua. "
        "Kalau fakta tra ada di sini, bilang jujur tra yakin — jangan mengarang.\n\n"
        + "\n\n".join(sections)
    )


def muat_pengetahuan_lokal(path: Path | str | None = None) -> str:
    """Baca database_papua.json dan kembalikan teks konteks untuk system instruction."""
    return format_papua_database_context(load_papua_database(path))


def database_stats(data: dict[str, list[str]]) -> dict[str, int]:
    return {key: len(data.get(key) or []) for key, _ in _SECTION_KEYS}


_MOP_FALLBACK = (
    "Adoo kawan, sa pung ingatan lagi penuh, tunggu sa ingat-ingat dulu ee!"
)


def ambil_mop_acak_dari_database(path: Path | str | None = None) -> str:
    """Pengacak Mop dari database_papua.json (Raja Mop — setara Kotlin randomizer)."""
    items = load_papua_database(path).get("mop_list") or []
    if not items:
        return _MOP_FALLBACK
    import random

    return random.choice(items)
