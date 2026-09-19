"""Tests for turn memory commit hook."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from persona_ai.memory.commit_turn import commit_user_turn_memory
from persona_ai.memory.engine import list_memories, reset_memory_store
from persona_ai.memory.open_loop_engine import list_pending_open_loops, reset_open_loop_store
from persona_ai.runtime import PersonaRuntime
from persona_ai.session.store import InMemorySessionStore


@pytest.fixture
def memory_db(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        reset_memory_store()
        reset_open_loop_store()
        yield
        reset_memory_store()
        reset_open_loop_store()


def test_commit_user_turn_memory_no_keyword_extract(memory_db):
    facts, loops = commit_user_turn_memory(
        "Ingat ya, ko alergi seafood. Minggu depan sa mo kirim dokumen ke kantor.",
        session_id="s1",
    )
    assert facts == []
    assert loops == []
    assert list_memories() == []
    assert list_pending_open_loops() == []


def test_runtime_process_turn_does_not_auto_extract(memory_db, monkeypatch):
    runtime = PersonaRuntime(session_store=InMemorySessionStore())
    runtime.process_turn(
        "sess-1",
        "Ingat dong, nama ko Obet. Lusa sa ada rapat dengan tim.",
        channel="text",
    )
    assert list_memories() == []
    assert list_pending_open_loops() == []
