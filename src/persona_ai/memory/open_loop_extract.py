"""Open-loop candidates — structured records only, no chat keyword rules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpenLoopCandidate:
    topic: str
    content: str
    time_hint: str | None
    confidence: float


def extract_open_loop_candidates(text: str) -> list[OpenLoopCandidate]:
    """Intentionally empty — loops come from post-call JSON or manual/API create."""
    return []
