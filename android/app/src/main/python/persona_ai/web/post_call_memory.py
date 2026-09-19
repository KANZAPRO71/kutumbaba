"""Persist episodic memory and open loops after a voice call ends."""

from __future__ import annotations

import logging
from typing import Any

from persona_ai.memory.engine import commit_episodic
from persona_ai.memory.post_call_ingest import ingest_user_memories_from_post_call
from persona_ai.memory.open_loop_engine import create_open_loop
from persona_ai.memory.open_loop_extract import OpenLoopCandidate
from persona_ai.runtime import PersonaRuntime
from persona_ai.web.session_memory import post_call_summary

_log = logging.getLogger(__name__)


def _ingest_llm_open_loops(data: dict[str, Any], *, session_id: str) -> int:
    raw = data.get("open_loops")
    if not isinstance(raw, list):
        return 0
    saved = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        if item.get("from_user") is not True:
            continue
        topic = str(item.get("topic") or "").strip().lower()
        content = " ".join(str(item.get("content") or "").split()).strip()
        if len(topic) < 2 or len(content) < 8:
            continue
        hint_raw = item.get("time_hint")
        time_hint = str(hint_raw).strip() if hint_raw else None
        record = create_open_loop(
            OpenLoopCandidate(
                topic=topic,
                content=content,
                time_hint=time_hint or None,
                confidence=0.88,
            ),
            session_id=session_id,
        )
        if record and record.status == "pending":
            saved += 1
    return saved


def ingest_post_call_memory(
    runtime: PersonaRuntime,
    session_id: str,
    payload: dict[str, Any] | None,
) -> dict[str, int]:
    """
    After a call:
    - episodic row from post-call summary text
    - open loops from data.open_loops[]
    - durable facts from data.user_memories[] (LLM, validated — no regex on chat)
    """
    counts = {
        "episodic": 0,
        "open_loops": 0,
        "open_loops_llm": 0,
        "facts_llm": 0,
        "facts_review": 0,
    }
    if not isinstance(payload, dict):
        return counts

    data = payload.get("data")
    if isinstance(data, dict):
        counts["open_loops_llm"] = _ingest_llm_open_loops(data, session_id=session_id)
        counts["open_loops"] += counts["open_loops_llm"]
        saved_facts, queued = ingest_user_memories_from_post_call(data, session_id=session_id)
        counts["facts_llm"] = len(saved_facts)
        counts["facts_review"] = queued

    summary = post_call_summary(payload)
    if summary and commit_episodic(summary, session_id=session_id):
        counts["episodic"] = 1

    duration_ms = int(payload.get("duration_ms") or 0)
    try:
        from persona_ai.conversation.companion_stats import record_companion_session

        record_companion_session(duration_ms=duration_ms)
    except Exception:
        _log.debug("companion stats update skipped session=%s", session_id)

    if any(counts.values()) or duration_ms > 0:
        _log.info(
            "post-call memory ingest session=%s episodic=%s loops=%s facts=%s review=%s",
            session_id,
            counts["episodic"],
            counts["open_loops"],
            counts["facts_llm"],
            counts["facts_review"],
        )
    return counts
