"""User memory engine — local facts persisted on the user's phone."""

from __future__ import annotations

import logging
from typing import Any

from persona_ai.memory.extract import extract_memory_candidates
from persona_ai.memory.models import DEFAULT_USER_ID, MemorySource, MemoryType, UserMemoryRecord
from persona_ai.memory.store import SQLiteUserMemoryStore, default_memory_db_path

_log = logging.getLogger(__name__)

_store: SQLiteUserMemoryStore | None = None
MAX_PROMPT_MEMORIES = 40
MAX_CONTENT_CHARS = 220

_TYPE_LABELS_PAPUA = {
    "semantic": "fakta",
    "preference": "suka/tidak suka",
    "episodic": "obrolan lalu",
    "manual": "ko simpan",
}

_TYPE_LABELS_EN = {
    "semantic": "fact",
    "preference": "preference",
    "episodic": "past chat",
    "manual": "saved note",
}


def get_memory_store() -> SQLiteUserMemoryStore:
    global _store
    if _store is None:
        _store = SQLiteUserMemoryStore(default_memory_db_path())
    return _store


def reset_memory_store() -> None:
    """Release singleton — tests and hot reload."""
    global _store
    if _store is not None:
        try:
            _store.close()
        except Exception:
            pass
    _store = None


def memory_storage_path() -> str:
    return str(default_memory_db_path())


def list_memories(user_id: str = DEFAULT_USER_ID, *, limit: int = 100) -> list[UserMemoryRecord]:
    return get_memory_store().list_all(user_id, limit=limit)


def add_memory(
    content: str,
    *,
    memory_type: MemoryType = "manual",
    source: MemorySource = "manual",
    session_id: str | None = None,
    user_id: str = DEFAULT_USER_ID,
    confidence: float = 0.95,
) -> UserMemoryRecord | None:
    fact = " ".join((content or "").split()).strip()
    if len(fact) < 2:
        return None
    store = get_memory_store()
    existing = store.find_similar(fact, user_id)
    if existing:
        existing.content = fact
        existing.memory_type = memory_type
        existing.source = source
        existing.confidence = max(existing.confidence, confidence)
        if session_id:
            existing.session_id = session_id
        store.save(existing)
        return existing
    record = UserMemoryRecord(
        user_id=user_id,
        memory_type=memory_type,
        content=fact,
        confidence=confidence,
        source=source,
        session_id=session_id,
    )
    store.save(record)
    _log.info("user memory saved type=%s id=%s", memory_type, record.id)
    return record


def delete_memory(memory_id: str, user_id: str = DEFAULT_USER_ID) -> bool:
    return get_memory_store().delete(memory_id, user_id)


def commit_from_text(
    text: str,
    *,
    session_id: str | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> list[UserMemoryRecord]:
    saved: list[UserMemoryRecord] = []
    for candidate in extract_memory_candidates(text):
        record = add_memory(
            candidate.content,
            memory_type=candidate.memory_type,
            source=candidate.source,
            session_id=session_id,
            user_id=user_id,
            confidence=candidate.confidence,
        )
        if record:
            saved.append(record)
    return saved


def commit_episodic(
    summary: str,
    *,
    session_id: str | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> UserMemoryRecord | None:
    cleaned = " ".join((summary or "").split()).strip()
    if len(cleaned) < 12:
        return None
    return add_memory(
        cleaned,
        memory_type="episodic",
        source="post_call",
        session_id=session_id,
        user_id=user_id,
        confidence=0.72,
    )


def format_memory_block(
    records: list[UserMemoryRecord] | None,
    *,
    dialect: str | None = None,
) -> str:
    if not records:
        return ""
    papua = dialect and dialect.strip().lower() in {"papua", "papuan", "logat_papua", "papua_id"}
    lines: list[str] = []
    if papua:
        lines.extend(
            [
                "INGATAN KHUSUS KO (tersimpan di HP — pakai internal, jangan bilang tra ingat):",
                "- Fakta permanen tentang ko — lanjutkan obrolan natural.",
                "- Jangan bacakan ulang daftar ingatan; jangan konfirmasi 'siap ingat' kecuali ko minta.",
                "- Kalau ko tanya hal yang tersimpan, jawab singkat dan konsisten — sekali saja.",
            ]
        )
    else:
        lines.extend(
            [
                "USER MEMORY (stored on device — use internally, do not claim you forgot):",
                "- Permanent facts — reference when relevant, never read the list aloud.",
                "- Do not repeat confirmations like 'got it, I'll remember' unless asked.",
            ]
        )

    labels = _TYPE_LABELS_PAPUA if papua else _TYPE_LABELS_EN
    for record in records[:MAX_PROMPT_MEMORIES]:
        label = labels.get(record.memory_type, record.memory_type)
        content = record.content
        if len(content) > MAX_CONTENT_CHARS:
            content = content[: MAX_CONTENT_CHARS - 1] + "…"
        lines.append(f"· [{label}] {content}")
    return "\n".join(lines)


def load_memories_for_prompt(user_id: str = DEFAULT_USER_ID) -> list[UserMemoryRecord]:
    return list_memories(user_id, limit=MAX_PROMPT_MEMORIES)


def memory_summary_for_client(records: list[UserMemoryRecord]) -> list[dict[str, Any]]:
    return [
        {
            "id": r.id,
            "content": r.content,
            "memory_type": r.memory_type,
            "source": r.source,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in records
    ]
