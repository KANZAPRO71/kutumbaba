"""Restore local memory export (v2/v3) — merge or replace."""

from __future__ import annotations

import logging
from typing import Any, Literal

from persona_ai.conversation.companion_prefs import CompanionPrefs, save_companion_prefs
from persona_ai.conversation.companion_stats import CompanionStats, get_companion_stats_store
from persona_ai.memory.engine import clear_all_user_memory, get_memory_store
from persona_ai.memory.models import DEFAULT_USER_ID, UserMemoryRecord
from persona_ai.memory.open_loop_engine import get_open_loop_store
from persona_ai.memory.open_loop_models import OpenLoopRecord
from persona_ai.memory.review_engine import get_review_store
from persona_ai.memory.review_models import MemoryReviewRecord, ReviewMemoryType

_log = logging.getLogger(__name__)

_SUPPORTED_SCHEMAS = frozenset(
    {"papua_ai_memory_export_v2", "papua_ai_memory_export_v3"},
)
ImportMode = Literal["merge", "replace"]


def _validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("import payload must be a JSON object")
    schema = str(payload.get("schema_version") or "").strip()
    if schema not in _SUPPORTED_SCHEMAS:
        raise ValueError(f"unsupported export schema: {schema or 'missing'}")
    return payload


def _import_memories(
    items: list[Any],
    *,
    mode: ImportMode,
    user_id: str,
) -> int:
    store = get_memory_store()
    existing_norm = set()
    if mode == "merge":
        from persona_ai.memory.engine import list_memories

        for row in list_memories(user_id, limit=500):
            existing_norm.add(row.content.strip().lower())

    saved = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        content = " ".join(str(item.get("content") or "").split()).strip()
        if len(content) < 2:
            continue
        if mode == "merge" and content.lower() in existing_norm:
            continue
        memory_type = str(item.get("memory_type") or "manual")
        if memory_type not in {"semantic", "preference", "relationship", "episodic", "manual"}:
            memory_type = "manual"
        source = str(item.get("source") or "manual")
        record = UserMemoryRecord(
            id=str(item.get("id") or UserMemoryRecord().id),
            user_id=user_id,
            memory_type=memory_type,  # type: ignore[arg-type]
            content=content,
            source=source,  # type: ignore[arg-type]
            created_at=str(item.get("created_at") or ""),
            updated_at=str(item.get("updated_at") or ""),
        )
        store.save(record)
        try:
            from persona_ai.memory.embedding_index import index_memory_vector

            index_memory_vector(record)
        except Exception:
            pass
        existing_norm.add(content.lower())
        saved += 1
    return saved


def _import_open_loops(items: list[Any], *, mode: ImportMode, user_id: str) -> int:
    store = get_open_loop_store()
    existing_norm: set[str] = set()
    if mode == "merge":
        for row in store.list_by_status(user_id, status="pending", limit=200):
            existing_norm.add(row.content.strip().lower())

    saved = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        content = " ".join(str(item.get("content") or "").split()).strip()
        topic = str(item.get("topic") or "").strip().lower()
        if len(content) < 8 or len(topic) < 2:
            continue
        if mode == "merge" and content.lower() in existing_norm:
            continue
        status = str(item.get("status") or "pending")
        if status not in {"pending", "resolved", "expired"}:
            status = "pending"
        record = OpenLoopRecord(
            id=str(item.get("id") or OpenLoopRecord().id),
            user_id=user_id,
            topic=topic,
            content=content,
            status=status,  # type: ignore[arg-type]
            time_hint=item.get("time_hint"),
            created_at=str(item.get("created_at") or ""),
            updated_at=str(item.get("updated_at") or ""),
        )
        store.save(record)
        try:
            from persona_ai.memory.embedding_index import index_open_loop_vector

            index_open_loop_vector(record)
        except Exception:
            pass
        existing_norm.add(content.lower())
        saved += 1
    return saved


def _import_review_queue(items: list[Any], *, user_id: str) -> int:
    saved = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        content = " ".join(str(item.get("content") or "").split()).strip()
        if len(content) < 8:
            continue
        mtype = str(item.get("memory_type") or "semantic")
        if mtype not in {"semantic", "preference", "relationship"}:
            mtype = "semantic"
        confidence = float(item.get("confidence") or 0.8)
        record = MemoryReviewRecord(
            id=str(item.get("id") or MemoryReviewRecord().id),
            user_id=user_id,
            content=content,
            memory_type=mtype,  # type: ignore[arg-type]
            confidence=confidence,
            created_at=str(item.get("created_at") or ""),
        )
        get_review_store().save(record)
        saved += 1
    return saved


def _import_companion_stats(block: Any) -> bool:
    if not isinstance(block, dict):
        return False
    stats = CompanionStats(
        streak_days=int(block.get("streak_days") or 0),
        last_talk_date=str(block.get("last_talk_date") or ""),
        total_sessions=int(block.get("total_sessions") or 0),
        total_duration_ms=int(block.get("minutes_talked") or 0) * 60_000,
    )
    get_companion_stats_store().save(stats)
    return True


def _import_prefs(block: Any) -> bool:
    if not isinstance(block, dict):
        return False
    prefs = CompanionPrefs.model_validate(
        {
            "rag_enabled": block.get("rag_enabled", True),
            "rag_min_score": block.get("rag_min_score", 0.18),
            "rag_use_gemini": block.get("rag_use_gemini", False),
        },
    )
    save_companion_prefs(prefs)
    return True


def _import_feedback(items: list[Any]) -> int:
    from persona_ai.conversation.companion_prefs import get_companion_prefs_store

    store = get_companion_prefs_store()
    count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("session_id") or "").strip()
        rating = str(item.get("rating") or "").strip()
        if sid and rating in {"up", "down", "skip"}:
            store.record_feedback(sid, rating)
            count += 1
    return count


def import_user_data(
    payload: dict[str, Any],
    *,
    mode: ImportMode = "merge",
    user_id: str = DEFAULT_USER_ID,
) -> dict[str, int]:
    """Restore export JSON. replace wipes local memory first."""
    data = _validate_payload(payload)
    counts = {
        "memories": 0,
        "open_loops": 0,
        "review": 0,
        "feedback": 0,
    }

    if mode == "replace":
        clear_all_user_memory(user_id)
        from persona_ai.conversation.companion_prefs import get_companion_prefs_store

        get_companion_prefs_store().delete_all()

    memories_raw = data.get("memories")
    if isinstance(memories_raw, list):
        counts["memories"] = _import_memories(memories_raw, mode=mode, user_id=user_id)

    loops_raw = data.get("open_loops")
    if isinstance(loops_raw, list):
        counts["open_loops"] = _import_open_loops(loops_raw, mode=mode, user_id=user_id)

    if mode == "replace":
        companion = data.get("companion")
        if _import_companion_stats(companion):
            counts["companion_stats"] = 1

        prefs = data.get("companion_prefs")
        if isinstance(prefs, dict) and _import_prefs(prefs):
            counts["companion_prefs"] = 1

        review_raw = data.get("memory_review_queue")
        if isinstance(review_raw, list):
            counts["review"] = _import_review_queue(review_raw, user_id=user_id)

        feedback_raw = data.get("session_feedback")
        if isinstance(feedback_raw, list):
            counts["feedback"] = _import_feedback(feedback_raw)

    _log.info("memory import mode=%s counts=%s", mode, counts)
    return counts
