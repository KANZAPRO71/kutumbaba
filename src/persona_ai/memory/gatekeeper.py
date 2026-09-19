"""Filter prompt memories by semantic similarity — gate irrelevant rows out."""

from __future__ import annotations

import os

from persona_ai.memory.embedding_index import embed_query, vector_for_memory, vector_for_open_loop
from persona_ai.memory.models import UserMemoryRecord
from persona_ai.memory.open_loop_models import OpenLoopRecord
from persona_ai.memory.vector_math import cosine_similarity

_DEFAULT_MIN_SCORE = 0.18


def min_rag_score() -> float:
    raw = (os.environ.get("PERSONA_MEMORY_RAG_MIN_SCORE") or "").strip()
    if raw:
        try:
            return max(0.05, min(0.95, float(raw)))
        except ValueError:
            pass
    try:
        from persona_ai.conversation.companion_prefs import load_companion_prefs

        return float(load_companion_prefs().rag_min_score)
    except Exception:
        return _DEFAULT_MIN_SCORE


def rag_enabled() -> bool:
    raw = (os.environ.get("PERSONA_MEMORY_RAG") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    try:
        from persona_ai.conversation.companion_prefs import load_companion_prefs

        return bool(load_companion_prefs().rag_enabled)
    except Exception:
        return True


def select_memories_for_query(
    records: list[UserMemoryRecord],
    query: str,
    *,
    limit: int,
) -> tuple[list[UserMemoryRecord], float | None]:
    cleaned = " ".join((query or "").split()).strip()
    if not cleaned or not records:
        return [], None
    q_vec = embed_query(cleaned)
    scored: list[tuple[UserMemoryRecord, float]] = []
    for record in records:
        score = cosine_similarity(q_vec, vector_for_memory(record))
        scored.append((record, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    threshold = min_rag_score()
    picked = [r for r, s in scored if s >= threshold][:limit]
    top_score = scored[0][1] if scored else None
    if picked:
        return picked, top_score
    return [], top_score


def select_open_loops_for_query(
    records: list[OpenLoopRecord],
    query: str,
    *,
    limit: int,
) -> tuple[list[OpenLoopRecord], float | None]:
    cleaned = " ".join((query or "").split()).strip()
    if not cleaned or not records:
        return [], None
    q_vec = embed_query(cleaned)
    scored: list[tuple[OpenLoopRecord, float]] = []
    for record in records:
        score = cosine_similarity(q_vec, vector_for_open_loop(record))
        scored.append((record, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    threshold = min_rag_score()
    picked = [r for r, s in scored if s >= threshold][:limit]
    top_score = scored[0][1] if scored else None
    if picked:
        return picked, top_score
    return [], top_score
