"""Confirm or dismiss LLM memory suggestions."""

from __future__ import annotations

import logging

from persona_ai.memory.engine import add_memory
from persona_ai.memory.models import DEFAULT_USER_ID, UserMemoryRecord
from persona_ai.memory.review_models import MemoryReviewRecord, ReviewMemoryType
from persona_ai.memory.review_store import SQLiteMemoryReviewStore

_log = logging.getLogger(__name__)

_store: SQLiteMemoryReviewStore | None = None


def get_review_store() -> SQLiteMemoryReviewStore:
    global _store
    if _store is None:
        _store = SQLiteMemoryReviewStore()
    return _store


def reset_review_store() -> None:
    global _store
    if _store is not None:
        try:
            _store.close()
        except Exception:
            pass
    _store = None


def queue_memory_review(
    content: str,
    *,
    memory_type: ReviewMemoryType = "semantic",
    confidence: float = 0.8,
    session_id: str | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> MemoryReviewRecord | None:
    fact = " ".join((content or "").split()).strip()
    if len(fact) < 8:
        return None
    for existing in list_memory_reviews(user_id, limit=100):
        if existing.content.strip().lower() == fact.lower():
            return existing
    record = MemoryReviewRecord(
        user_id=user_id,
        content=fact,
        memory_type=memory_type,
        confidence=confidence,
        session_id=session_id,
    )
    get_review_store().save(record)
    _log.info("memory review queued id=%s", record.id)
    return record


def list_memory_reviews(
    user_id: str = DEFAULT_USER_ID,
    *,
    limit: int = 30,
) -> list[MemoryReviewRecord]:
    return get_review_store().list_all(user_id, limit=limit)


def confirm_memory_review(review_id: str, user_id: str = DEFAULT_USER_ID) -> UserMemoryRecord | None:
    store = get_review_store()
    pending = store.get(review_id, user_id)
    if pending is None:
        return None
    saved = add_memory(
        pending.content,
        memory_type=pending.memory_type,
        source="post_call",
        session_id=pending.session_id,
        user_id=user_id,
        confidence=max(pending.confidence, 0.9),
    )
    store.delete(review_id, user_id)
    return saved


def dismiss_memory_review(review_id: str, user_id: str = DEFAULT_USER_ID) -> bool:
    return get_review_store().delete(review_id, user_id)
