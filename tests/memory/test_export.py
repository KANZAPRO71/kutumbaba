"""Tests for memory export and clear-all."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from persona_ai.memory.engine import (
    add_memory,
    clear_all_user_memory,
    export_user_data,
    list_memories,
    reset_memory_store,
)
from persona_ai.memory.open_loop_engine import (
    list_pending_open_loops,
    reset_open_loop_store,
)


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


def test_export_and_clear(memory_db):
    add_memory("Nama ko Budi", memory_type="manual")
    from persona_ai.memory.open_loop_engine import create_open_loop
    from persona_ai.memory.open_loop_extract import OpenLoopCandidate

    create_open_loop(
        OpenLoopCandidate(
            topic="rapat",
            content="Lusa sa ada rapat dengan tim",
            time_hint="lusa",
            confidence=0.9,
        ),
    )
    exported = export_user_data()
    assert exported["schema_version"] == "papua_ai_memory_export_v3"
    assert len(exported["memories"]) == 1
    assert len(exported["open_loops"]) == 1
    assert "companion_prefs" in exported
    assert "session_feedback" in exported
    assert "memory_review_queue" in exported
    assert "companion" in exported
    assert "achievements" in exported["companion"]
    assert len(exported["companion"]["achievements"]) == 5

    counts = clear_all_user_memory()
    assert counts["memories_deleted"] >= 1
    assert counts["open_loops_deleted"] >= 1
    assert list_memories() == []
    assert list_pending_open_loops() == []
