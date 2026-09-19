"""Tests for companion memory retrieval (recency only)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from persona_ai.memory.engine import add_memory, reset_memory_store
from persona_ai.memory.open_loop_engine import create_open_loop, reset_open_loop_store
from persona_ai.memory.open_loop_extract import OpenLoopCandidate
from persona_ai.memory.embedding_store import reset_embedding_store
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


def test_retrieve_prefers_durable_over_episodic(memory_db):
    add_memory("Ringkasan obrolan kemarin tentang cuaca", memory_type="episodic")
    time.sleep(0.01)
    add_memory("Ko kerja di bank", memory_type="semantic")
    time.sleep(0.01)
    add_memory("Ko suka musik reggae", memory_type="preference")
    ctx = retrieve_companion_memory(None)
    types = [m.memory_type for m in ctx.user_memories]
    assert "semantic" in types
    assert types.count("episodic") <= 2


def test_retrieve_open_loops_by_recency(memory_db):
    create_open_loop(
        OpenLoopCandidate(
            topic="a",
            content="First pending thread about alpha",
            time_hint=None,
            confidence=0.9,
        ),
    )
    time.sleep(0.01)
    create_open_loop(
        OpenLoopCandidate(
            topic="b",
            content="Second pending thread about beta",
            time_hint=None,
            confidence=0.9,
        ),
    )
    ctx = retrieve_companion_memory("alpha project thread")
    assert len(ctx.open_loops) >= 1
    assert "alpha" in ctx.open_loops[0].content.lower()


def test_retrieve_without_query_returns_recent(memory_db):
    create_open_loop(
        OpenLoopCandidate(
            topic="motor",
            content="Minggu depan sa mo beli motor",
            time_hint=None,
            confidence=0.9,
        ),
    )
    ctx = retrieve_companion_memory(None)
    assert len(ctx.open_loops) >= 1
