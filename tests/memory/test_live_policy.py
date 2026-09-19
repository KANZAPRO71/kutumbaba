"""Live memory injection policy."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from persona_ai.memory.engine import add_memory, reset_memory_store
from persona_ai.memory.live_policy import apply_live_memory_policy
from persona_ai.memory.models import UserMemoryRecord
from persona_ai.memory.retrieve import CompanionMemoryContext, retrieve_companion_memory
from persona_ai.web.session_memory import format_companion_context_block, load_companion_context_for_turn


@pytest.fixture
def memory_db(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        monkeypatch.setenv("PERSONA_MEMORY_RAG", "1")
        from persona_ai.memory.embedding_store import reset_embedding_store
        from persona_ai.memory.open_loop_engine import reset_open_loop_store

        reset_memory_store()
        reset_open_loop_store()
        reset_embedding_store()
        yield
        reset_memory_store()
        reset_open_loop_store()
        reset_embedding_store()


def test_semantic_empty_returns_no_block(memory_db):
    add_memory("Ko suka reggae di festival", memory_type="preference")
    ctx = load_companion_context_for_turn("cuaca hari ini panas", messages=[])
    block = format_companion_context_block(ctx, dialect="papua")
    assert block == ""


def test_policy_caps_rows():
    mems = tuple(
        UserMemoryRecord(content=f"Fact number {i}", memory_type="semantic")
        for i in range(10)
    )
    ctx = CompanionMemoryContext(
        user_memories=mems,
        open_loops=(),
        query="test",
        retrieval_mode="recency",
    )
    trimmed = apply_live_memory_policy(ctx)
    assert len(trimmed.user_memories) <= 4
