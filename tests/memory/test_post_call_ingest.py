"""Tests for LLM post-call memory validation (no chat regex)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from persona_ai.memory.engine import list_memories, reset_memory_store
from persona_ai.memory.post_call_ingest import (
    ingest_user_memories_from_post_call,
    normalize_post_call_memory_item,
)
from persona_ai.memory.review_engine import list_memory_reviews, reset_review_store


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


def test_normalize_rejects_short_and_low_confidence():
    assert normalize_post_call_memory_item({"content": "hi", "memory_type": "semantic"}) is None
    assert (
        normalize_post_call_memory_item(
            {"content": "Ko alergi seafood", "memory_type": "semantic", "confidence": 0.2},
        )
        is None
    )


def test_ingest_user_memories(memory_db):
    data = {
        "user_memories": [
            {
                "content": "Nama ko Obet, tinggal di Jayapura",
                "memory_type": "semantic",
                "confidence": 0.92,
                "from_user": True,
            },
            {
                "content": "Ko tra suka pedas",
                "memory_type": "preference",
                "confidence": 0.88,
                "from_user": True,
            },
        ],
    }
    saved, queued = ingest_user_memories_from_post_call(data, session_id="s-post")
    assert len(saved) == 2
    assert queued == 0
    items = list_memories()
    assert len(items) == 2
    assert any(m.memory_type == "preference" for m in items)
    assert all(m.source == "post_call" for m in items)


def test_rejects_agent_inferred_facts(memory_db):
    data = {
        "user_memories": [
            {
                "content": "Ko pasti suka hiking di pegunungan",
                "memory_type": "preference",
                "confidence": 0.95,
                "from_user": False,
            },
        ],
    }
    saved, queued = ingest_user_memories_from_post_call(data, session_id="s-no")
    assert saved == []
    assert queued == 0
    assert list_memories() == []


def test_low_confidence_goes_to_review_queue(memory_db):
    data = {
        "user_memories": [
            {
                "content": "Ko mungkin suka hiking di pegunungan",
                "memory_type": "preference",
                "confidence": 0.75,
                "from_user": True,
            },
        ],
    }
    saved, queued = ingest_user_memories_from_post_call(data, session_id="s-review")
    assert saved == []
    assert queued == 1
    assert list_memories() == []
    assert len(list_memory_reviews()) == 1
