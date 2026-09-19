"""Validate and persist structured memory from post-call LLM JSON (no regex on chat)."""

from __future__ import annotations

from typing import Any

from persona_ai.memory.engine import add_memory
from persona_ai.memory.models import MemoryType, UserMemoryRecord

_POST_CALL_FACT_TYPES: frozenset[MemoryType] = frozenset(
    {"semantic", "preference", "relationship"},
)
_MIN_CONTENT_LEN = 8
_MAX_CONTENT_LEN = 280
_MIN_CONFIDENCE = 0.65
_AUTO_SAVE_CONFIDENCE = 0.85
_MAX_ITEMS = 12


def _clamp_confidence(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.85
    return max(0.0, min(1.0, value))


def _from_user_confirmed(item: dict[str, Any]) -> bool:
    raw = item.get("from_user")
    if raw is True:
        return True
    if raw is False:
        return False
    return False


def normalize_post_call_memory_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    if not _from_user_confirmed(item):
        return None
    content = " ".join(str(item.get("content") or "").split()).strip()
    if len(content) < _MIN_CONTENT_LEN:
        return None
    if len(content) > _MAX_CONTENT_LEN:
        content = content[: _MAX_CONTENT_LEN - 1] + "…"
    memory_type = str(item.get("memory_type") or "semantic").strip().lower()
    if memory_type not in _POST_CALL_FACT_TYPES:
        memory_type = "semantic"
    confidence = _clamp_confidence(item.get("confidence", 0.85))
    if confidence < _MIN_CONFIDENCE:
        return None
    return {
        "content": content,
        "memory_type": memory_type,
        "confidence": confidence,
    }


def ingest_user_memories_from_post_call(
    data: dict[str, Any],
    *,
    session_id: str | None = None,
) -> tuple[list[UserMemoryRecord], int]:
    """Persist durable facts from data.user_memories[] after LLM extraction."""
    from persona_ai.memory.review_engine import queue_memory_review

    raw = data.get("user_memories")
    if not isinstance(raw, list) or not raw:
        return [], 0
    saved: list[UserMemoryRecord] = []
    queued = 0
    for item in raw[: _MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        normalized = normalize_post_call_memory_item(item)
        confidence = _clamp_confidence(item.get("confidence", 0.85))
        if normalized is None:
            if item.get("from_user") is False:
                continue
            content = " ".join(str(item.get("content") or "").split()).strip()
            if len(content) >= _MIN_CONTENT_LEN and confidence >= _MIN_CONFIDENCE:
                memory_type = str(item.get("memory_type") or "semantic").strip().lower()
                if memory_type not in _POST_CALL_FACT_TYPES:
                    memory_type = "semantic"
                if queue_memory_review(
                    content,
                    memory_type=memory_type,  # type: ignore[arg-type]
                    confidence=min(confidence, 0.84),
                    session_id=session_id,
                ):
                    queued += 1
            continue
        confidence = float(normalized["confidence"])
        memory_type = normalized["memory_type"]
        content = normalized["content"]
        if confidence >= _AUTO_SAVE_CONFIDENCE:
            record = add_memory(
                content,
                memory_type=memory_type,
                source="post_call",
                session_id=session_id,
                confidence=confidence,
            )
            if record:
                saved.append(record)
        else:
            if queue_memory_review(
                content,
                memory_type=memory_type,
                confidence=confidence,
                session_id=session_id,
            ):
                queued += 1
    return saved, queued
