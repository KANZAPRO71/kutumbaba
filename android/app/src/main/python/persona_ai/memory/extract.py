"""Rule-based memory extraction from user utterances."""

from __future__ import annotations

import re
from dataclasses import dataclass

from persona_ai.memory.models import MemorySource, MemoryType


@dataclass(frozen=True)
class MemoryCandidate:
    content: str
    memory_type: MemoryType
    confidence: float
    source: MemorySource


_PATTERNS: list[tuple[re.Pattern[str], MemoryType, float]] = [
    (
        re.compile(
            r"(?:ingat|catat|simpen)\s+(?:ya|dong|dulu|baik|nih|deh|ini|tuh)\s*[,:]?\s*(.+)",
            re.I,
        ),
        "semantic",
        0.95,
    ),
    (re.compile(r"jangan\s+lupa\s*[,:]?\s*(.+)", re.I), "semantic", 0.95),
    (re.compile(r"remember\s+(?:that\s+)?(.+)", re.I), "semantic", 0.95),
    (
        re.compile(
            r"(?:nama\s+(?:saya|ku|ko)|panggil\s+(?:saya|aku|ko))\s+(?:adalah|itu|ya|namanya)?\s*(.+)",
            re.I,
        ),
        "semantic",
        0.88,
    ),
    (
        re.compile(r"(?:saya|aku|ko)\s+(?:suka|senang|do[\s']?yan|sukanya)\s+(.+)", re.I),
        "preference",
        0.85,
    ),
    (
        re.compile(
            r"(?:saya|aku|ko)\s+(?:tra|tidak|gak|nggak|enggak)\s+suka\s+(.+)",
            re.I,
        ),
        "preference",
        0.85,
    ),
    (
        re.compile(r"(?:saya|aku|ko)\s+(?:kerja|bekerja|kuliah)\s+(?:di|ke)\s+(.+)", re.I),
        "semantic",
        0.8,
    ),
    (
        re.compile(r"(?:saya|aku|ko)\s+(?:tinggal|domisili|dari)\s+(?:di|ke)?\s*(.+)", re.I),
        "semantic",
        0.8,
    ),
]


def _clean_fact(text: str) -> str:
    cleaned = " ".join(text.split()).strip(" .,!?:;\"'")
    if len(cleaned) > 280:
        cleaned = cleaned[:277] + "…"
    return cleaned


def extract_memory_candidates(text: str) -> list[MemoryCandidate]:
    """Auto-extraction disabled — continuity comes from session transcript only."""
    del text
    return []
