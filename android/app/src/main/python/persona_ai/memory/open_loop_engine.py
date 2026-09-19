"""Open-loop lifecycle — create, resolve, expire, prompt formatting."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from persona_ai.memory.models import DEFAULT_USER_ID
from persona_ai.memory.open_loop_extract import OpenLoopCandidate
from persona_ai.memory.open_loop_models import OpenLoopRecord
from persona_ai.memory.open_loop_store import SQLiteOpenLoopStore

_log = logging.getLogger(__name__)

_store: SQLiteOpenLoopStore | None = None
MAX_PROMPT_OPEN_LOOPS = 8
DEFAULT_EXPIRE_DAYS = 21


def get_open_loop_store() -> SQLiteOpenLoopStore:
    global _store
    if _store is None:
        _store = SQLiteOpenLoopStore()
    return _store


def reset_open_loop_store() -> None:
    global _store
    if _store is not None:
        try:
            _store.close()
        except Exception:
            pass
    _store = None


def list_pending_open_loops(
    user_id: str = DEFAULT_USER_ID,
    *,
    limit: int = MAX_PROMPT_OPEN_LOOPS,
) -> list[OpenLoopRecord]:
    expire_stale_open_loops(user_id=user_id)
    return get_open_loop_store().list_by_status(user_id, status="pending", limit=limit)


def create_open_loop(
    candidate: OpenLoopCandidate,
    *,
    session_id: str | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> OpenLoopRecord | None:
    content = " ".join((candidate.content or "").split()).strip()
    if len(content) < 8:
        return None
    store = get_open_loop_store()
    norm = content.lower()
    existing = store.find_pending_by_topic(candidate.topic, user_id)
    if existing is None:
        for record in store.list_by_status(user_id, status="pending", limit=100):
            if record.content.strip().lower() == norm:
                existing = record
                break
    if existing:
        existing.content = content
        existing.time_hint = candidate.time_hint or existing.time_hint
        existing.confidence = max(existing.confidence, candidate.confidence)
        if session_id:
            existing.session_id = session_id
        store.save(existing)
        _log.info("open loop updated topic=%s id=%s", candidate.topic, existing.id)
        try:
            from persona_ai.memory.embedding_index import index_open_loop_vector

            index_open_loop_vector(existing)
        except Exception:
            pass
        return existing
    record = OpenLoopRecord(
        user_id=user_id,
        topic=candidate.topic,
        content=content,
        time_hint=candidate.time_hint,
        session_id=session_id,
        confidence=candidate.confidence,
    )
    store.save(record)
    _log.info("open loop created topic=%s id=%s", record.topic, record.id)
    try:
        from persona_ai.memory.embedding_index import index_open_loop_vector

        index_open_loop_vector(record)
    except Exception:
        pass
    return record


def resolve_open_loop(
    loop_id: str,
    *,
    user_id: str = DEFAULT_USER_ID,
) -> OpenLoopRecord | None:
    store = get_open_loop_store()
    record = store.get(loop_id, user_id)
    if record is None or record.status != "pending":
        return None
    now = datetime.now(timezone.utc).isoformat()
    record.status = "resolved"
    record.resolved_at = now
    store.save(record)
    return record


def update_open_loop(
    loop_id: str,
    *,
    content: str | None = None,
    time_hint: str | None = None,
    user_id: str = DEFAULT_USER_ID,
    resolve: bool = False,
) -> OpenLoopRecord | None:
    store = get_open_loop_store()
    record = store.get(loop_id, user_id)
    if record is None or record.status != "pending":
        return None
    if content:
        record.content = " ".join(content.split()).strip()
    if time_hint is not None:
        record.time_hint = time_hint or None
    if resolve:
        record.status = "resolved"
        record.resolved_at = datetime.now(timezone.utc).isoformat()
    store.save(record)
    return record


def cancel_open_loop_by_topic(
    topic_hint: str,
    note: str,
    *,
    user_id: str = DEFAULT_USER_ID,
) -> OpenLoopRecord | None:
    """Merge cancellation into the existing loop, then resolve — no duplicate fact."""
    store = get_open_loop_store()
    record = store.find_pending_by_topic(topic_hint, user_id)
    if record is None:
        return None
    merged = " ".join((note or record.content).split()).strip()
    return update_open_loop(record.id, content=merged, user_id=user_id, resolve=True)


def resolve_by_topic_hint(
    topic_hint: str,
    *,
    user_id: str = DEFAULT_USER_ID,
) -> OpenLoopRecord | None:
    store = get_open_loop_store()
    record = store.find_pending_by_topic(topic_hint, user_id)
    if record is None:
        return None
    return resolve_open_loop(record.id, user_id=user_id)


def expire_stale_open_loops(
    *,
    user_id: str = DEFAULT_USER_ID,
    max_age_days: int = DEFAULT_EXPIRE_DAYS,
) -> int:
    """Mark very old pending loops expired — avoids stale follow-ups."""
    store = get_open_loop_store()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    expired = 0
    for record in store.list_by_status(user_id, status="pending", limit=200):
        if not record.created_at:
            continue
        try:
            created = datetime.fromisoformat(record.created_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < cutoff:
            record.status = "expired"
            store.save(record)
            expired += 1
    return expired


def commit_open_loops_from_text(
    text: str,
    *,
    session_id: str | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> list[OpenLoopRecord]:
    """No-op on raw chat — use create_open_loop() with structured candidates."""
    del text, session_id, user_id
    return []


def mark_loop_callback_surfaced(loop_id: str, *, user_id: str = DEFAULT_USER_ID) -> None:
    store = get_open_loop_store()
    record = store.get(loop_id, user_id)
    if record is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    record.last_callback_at = now
    record.callback_count = int(record.callback_count or 0) + 1
    store.save(record)


def mark_loop_mentioned(loop_id: str, *, user_id: str = DEFAULT_USER_ID) -> None:
    store = get_open_loop_store()
    record = store.get(loop_id, user_id)
    if record is None:
        return
    record.last_mentioned_at = datetime.now(timezone.utc).isoformat()
    store.save(record)


def record_loop_callback_outcome(loop_id: str, outcome: str, *, user_id: str = DEFAULT_USER_ID) -> None:
    store = get_open_loop_store()
    record = store.get(loop_id, user_id)
    if record is None:
        return
    record.last_callback_outcome = outcome
    if outcome == "engaged":
        record.last_mentioned_at = datetime.now(timezone.utc).isoformat()
    store.save(record)


def format_open_loops_block(
    records: list[OpenLoopRecord] | None,
    *,
    dialect: str | None = None,
) -> str:
    """Naturalization hints — not text to read aloud verbatim."""
    if not records:
        return ""
    papua = dialect and dialect.strip().lower() in {"papua", "papuan", "logat_papua", "papua_id"}
    lines: list[str] = []
    if papua:
        lines.extend(
            [
                "URUSAN BELUM SELESAI (internal — lanjutkan natural, jangan bacakan daftar):",
                "- Kalau relevan, tanya singkat follow-up dari isi urusan di bawah — satu saja.",
                "- Satu pertanyaan saja; jangan sebut 'open loop' atau 'memory'.",
            ]
        )
    else:
        lines.extend(
            [
                "OPEN THREADS (internal — follow up naturally, never read this list aloud):",
                "- Ask one short follow-up when relevant; do not say 'memory' or 'database'.",
            ]
        )
    for record in records[:MAX_PROMPT_OPEN_LOOPS]:
        hint = f" ({record.time_hint})" if record.time_hint else ""
        lines.append(f"· [{record.topic}{hint}] {record.content}")
    return "\n".join(lines)
