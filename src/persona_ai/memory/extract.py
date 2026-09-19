"""Memory extraction — no keyword/regex inference on user text.

Facts enter memory only via:
  - manual UI / POST /api/memory
  - validated post-call structured fields
  - explicit future ingest pipelines (not pattern-matched chat)
"""

from __future__ import annotations

from dataclasses import dataclass

from persona_ai.memory.models import MemorySource, MemoryType


@dataclass(frozen=True)
class MemoryCandidate:
    content: str
    memory_type: MemoryType
    confidence: float
    source: MemorySource


def extract_memory_candidates(text: str) -> list[MemoryCandidate]:
    """Intentionally empty — keyword triggers removed (product policy)."""
    return []
