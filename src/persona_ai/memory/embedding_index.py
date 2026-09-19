"""Index / cache vectors when memories and open loops are saved."""

from __future__ import annotations

import logging
import os

from persona_ai.memory.embedding_store import get_embedding_store, text_fingerprint
from persona_ai.memory.gemini_embedder import gemini_embed_text
from persona_ai.memory.local_embedder import local_embed_text
from persona_ai.memory.models import DEFAULT_USER_ID, UserMemoryRecord
from persona_ai.memory.open_loop_models import OpenLoopRecord
from persona_ai.memory.vector_math import normalize

_log = logging.getLogger(__name__)


def use_gemini_embeddings() -> bool:
    flag = (os.environ.get("PERSONA_MEMORY_RAG_GEMINI") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    try:
        from persona_ai.conversation.companion_prefs import load_companion_prefs

        return bool(load_companion_prefs().rag_use_gemini)
    except Exception:
        return False


def _use_gemini_embed() -> bool:
    return use_gemini_embeddings()


def embed_for_storage(text: str, *, api_key: str | None = None) -> list[float]:
    if _use_gemini_embed():
        vec = gemini_embed_text(text, api_key=api_key)
        if vec:
            return normalize(vec)
    return local_embed_text(text)


def index_memory_vector(record: UserMemoryRecord) -> None:
    text = (record.content or "").strip()
    if len(text) < 2:
        return
    fp = text_fingerprint(text)
    store = get_embedding_store()
    vec = embed_for_storage(text)
    store.put("memory", record.id, vec, text_fp=fp, user_id=record.user_id)


def index_open_loop_vector(record: OpenLoopRecord) -> None:
    text = f"{record.topic} {record.content}".strip()
    if len(text) < 4:
        return
    fp = text_fingerprint(text)
    vec = embed_for_storage(text)
    get_embedding_store().put(
        "open_loop",
        record.id,
        vec,
        text_fp=fp,
        user_id=record.user_id,
    )


def vector_for_memory(record: UserMemoryRecord) -> list[float]:
    store = get_embedding_store()
    vec = store.get("memory", record.id, record.user_id)
    if vec is not None:
        return vec
    index_memory_vector(record)
    return store.get("memory", record.id, record.user_id) or local_embed_text(record.content)


def vector_for_open_loop(record: OpenLoopRecord) -> list[float]:
    store = get_embedding_store()
    vec = store.get("open_loop", record.id, record.user_id)
    if vec is not None:
        return vec
    index_open_loop_vector(record)
    return store.get("open_loop", record.id, record.user_id) or local_embed_text(
        f"{record.topic} {record.content}",
    )


def embed_query(text: str) -> list[float]:
    return embed_for_storage(text)


def reindex_all_embeddings(user_id: str = DEFAULT_USER_ID) -> dict[str, int]:
    """Rebuild cached vectors (after toggling Gemini embed or manual refresh)."""
    from persona_ai.memory.engine import list_memories
    from persona_ai.memory.open_loop_engine import list_pending_open_loops

    counts = {"memories": 0, "open_loops": 0}
    for record in list_memories(user_id, limit=500):
        index_memory_vector(record)
        counts["memories"] += 1
    for loop in list_pending_open_loops(user_id, limit=200):
        index_open_loop_vector(loop)
        counts["open_loops"] += 1
    _log.info(
        "embedding reindex user=%s memories=%s open_loops=%s",
        user_id,
        counts["memories"],
        counts["open_loops"],
    )
    return counts
