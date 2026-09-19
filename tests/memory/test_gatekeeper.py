"""Semantic gatekeeper for memory RAG."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from persona_ai.memory.engine import add_memory, list_memories, reset_memory_store
from persona_ai.memory.embedding_store import reset_embedding_store
from persona_ai.memory.gatekeeper import select_memories_for_query, select_open_loops_for_query
from persona_ai.memory.open_loop_engine import create_open_loop, reset_open_loop_store
from persona_ai.memory.open_loop_extract import OpenLoopCandidate
from persona_ai.memory.retrieve import retrieve_companion_memory


@pytest.fixture
def memory_db(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        monkeypatch.setenv("PERSONA_MEMORY_RAG", "1")
        reset_memory_store()
        reset_open_loop_store()
        reset_embedding_store()
        yield
        reset_memory_store()
        reset_open_loop_store()
        reset_embedding_store()


def test_gatekeeper_picks_matching_memory(memory_db):
    add_memory("Ko suka musik reggae dan festival lokal", memory_type="preference")
    add_memory("Ko kerja di bank sentral Jayapura", memory_type="semantic")
    picked, _ = select_memories_for_query(
        list_memories(),
        "musik reggae festival",
        limit=5,
    )
    assert picked
    assert any("reggae" in m.content.lower() for m in picked)


def test_retrieve_query_filters_irrelevant_open_loop(memory_db):
    create_open_loop(
        OpenLoopCandidate(
            topic="alpha",
            content="First pending thread about alpha project",
            time_hint=None,
            confidence=0.9,
        ),
    )
    create_open_loop(
        OpenLoopCandidate(
            topic="beta",
            content="Second pending thread about beta release",
            time_hint=None,
            confidence=0.9,
        ),
    )
    ctx = retrieve_companion_memory("alpha project")
    assert ctx.retrieval_mode == "semantic"
    assert ctx.open_loops
    assert "alpha" in ctx.open_loops[0].content.lower()


def test_retrieve_no_query_uses_recency(memory_db):
    add_memory("Fakta lama", memory_type="semantic")
    ctx = retrieve_companion_memory(None)
    assert ctx.retrieval_mode == "recency"
    assert ctx.user_memories
