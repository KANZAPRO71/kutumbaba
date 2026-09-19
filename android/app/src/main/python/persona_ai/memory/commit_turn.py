"""Side effects after a user turn — local memory commit (non-blocking, no LLM)."""

from __future__ import annotations

import logging

from persona_ai.memory.engine import commit_from_text
from persona_ai.memory.models import DEFAULT_USER_ID, UserMemoryRecord
from persona_ai.memory.open_loop_engine import commit_open_loops_from_text
from persona_ai.memory.open_loop_models import OpenLoopRecord

_log = logging.getLogger(__name__)


def commit_user_turn_memory(
    user_text: str,
    *,
    session_id: str | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> tuple[list[UserMemoryRecord], list[OpenLoopRecord]]:
    """Turn hook — no keyword inference; post-call / manual paths persist memory."""
    text = " ".join((user_text or "").split()).strip()
    if len(text) < 4:
        return [], []

    facts = commit_from_text(text, session_id=session_id, user_id=user_id)
    loops = commit_open_loops_from_text(text, session_id=session_id, user_id=user_id)
    if facts or loops:
        _log.debug(
            "turn memory commit session=%s facts=%d loops=%d",
            session_id or "-",
            len(facts),
            len(loops),
        )
    return facts, loops
