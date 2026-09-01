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
    """Return zero or more memory candidates from a user utterance."""
    raw = (text or "").strip()
    if len(raw) < 6:
        return []

    out: list[MemoryCandidate] = []
    seen: set[str] = set()
    for pattern, memory_type, confidence in _PATTERNS:
        match = pattern.search(raw)
        if not match:
            continue
        fact = _clean_fact(match.group(1))
        if len(fact) < 3:
            continue
        key = fact.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            MemoryCandidate(
                content=fact,
                memory_type=memory_type,
                confidence=confidence,
                source="user_explicit",
            )
        )

    if len(out) <= 1:
        return out

    out.sort(key=lambda c: (-c.confidence, -len(c.content)))
    filtered: list[MemoryCandidate] = []
    for cand in out:
        lower = cand.content.lower()
        if any(
            lower != other.content.lower()
            and (lower in other.content.lower() or other.content.lower() in lower)
            for other in filtered
        ):
            continue
        filtered.append(cand)
    return filtered
