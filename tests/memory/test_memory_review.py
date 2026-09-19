"""Memory review queue confirm/dismiss."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from persona_ai.memory.engine import list_memories, reset_memory_store
from persona_ai.memory.review_engine import (
    confirm_memory_review,
    dismiss_memory_review,
    queue_memory_review,
    reset_review_store,
)


@pytest.fixture
def memory_db(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        reset_memory_store()
        reset_review_store()
        yield
        reset_memory_store()
        reset_review_store()


def test_confirm_moves_to_user_memory(memory_db):
    pending = queue_memory_review(
        "Ko kerja remote dari Sorong",
        memory_type="semantic",
        confidence=0.78,
    )
    assert pending is not None
    saved = confirm_memory_review(pending.id)
    assert saved is not None
    assert list_memories()
    assert dismiss_memory_review(pending.id) is False


def test_dismiss_removes_queue(memory_db):
    pending = queue_memory_review("Ko suka kopi tanpa gula", memory_type="preference")
    assert pending is not None
    assert dismiss_memory_review(pending.id) is True
    assert list_memories() == []
