"""Retrieve memories and open loops — recency or semantic gatekeeper (RAG)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from persona_ai.memory.engine import list_memories
from persona_ai.memory.gatekeeper import (
    rag_enabled,
    select_memories_for_query,
    select_open_loops_for_query,
)
from persona_ai.memory.models import DEFAULT_USER_ID, UserMemoryRecord
from persona_ai.memory.open_loop_engine import list_pending_open_loops
from persona_ai.memory.open_loop_models import OpenLoopRecord

MAX_RETRIEVED_MEMORIES = 12
MAX_RETRIEVED_OPEN_LOOPS = 5
MAX_EPISODIC_IN_PROMPT = 2
MIN_QUERY_LEN_FOR_RAG = 4

_DURABLE_TYPES = frozenset({"semantic", "preference", "relationship", "manual"})
RetrievalMode = Literal["recency", "semantic", "semantic_empty"]


@dataclass(frozen=True)
class CompanionMemoryContext:
    user_memories: tuple[UserMemoryRecord, ...]
    open_loops: tuple[OpenLoopRecord, ...]
    query: str
    retrieval_mode: RetrievalMode = "recency"


def _by_recency_memories(records: list[UserMemoryRecord], *, limit: int) -> list[UserMemoryRecord]:
    if not records:
        return []
    ordered = sorted(records, key=lambda r: r.updated_at or r.created_at or "", reverse=True)
    durable = [r for r in ordered if r.memory_type in _DURABLE_TYPES]
    episodic = [r for r in ordered if r.memory_type == "episodic"]
    picked: list[UserMemoryRecord] = []
    for row in durable:
        if len(picked) >= limit:
            break
        picked.append(row)
    if len(picked) < limit:
        for row in episodic[:MAX_EPISODIC_IN_PROMPT]:
            if len(picked) >= limit:
                break
            picked.append(row)
    return picked


def _by_recency_loops(records: list[OpenLoopRecord], *, limit: int) -> list[OpenLoopRecord]:
    if not records:
        return []
    ordered = sorted(records, key=lambda r: r.updated_at or r.created_at or "", reverse=True)
    return ordered[:limit]


def retrieve_companion_memory(
    query: str | None = None,
    *,
    user_id: str = DEFAULT_USER_ID,
    max_memories: int = MAX_RETRIEVED_MEMORIES,
    max_open_loops: int = MAX_RETRIEVED_OPEN_LOOPS,
) -> CompanionMemoryContext:
    """Inject a small subset — semantic gate when query present, else recency tiers."""
    cleaned = " ".join((query or "").split()).strip()

    all_memories = list_memories(user_id, limit=80)
    pending_loops = list_pending_open_loops(user_id, limit=30)

    use_rag = rag_enabled() and len(cleaned) >= MIN_QUERY_LEN_FOR_RAG
    mode: RetrievalMode = "recency"

    if use_rag:
        memories, _ = select_memories_for_query(
            all_memories,
            cleaned,
            limit=max_memories,
        )
        loops, _ = select_open_loops_for_query(
            pending_loops,
            cleaned,
            limit=max_open_loops,
        )
        mode = "semantic" if memories or loops else "semantic_empty"
    else:
        memories = _by_recency_memories(all_memories, limit=max_memories)
        loops = _by_recency_loops(pending_loops, limit=max_open_loops)

    return CompanionMemoryContext(
        user_memories=tuple(memories),
        open_loops=tuple(loops),
        query=cleaned,
        retrieval_mode=mode,
    )
