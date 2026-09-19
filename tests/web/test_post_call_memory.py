"""Tests for post-call memory ingest."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from persona_ai.core.types import Message
from persona_ai.memory.engine import list_memories, reset_memory_store
from persona_ai.memory.open_loop_engine import list_pending_open_loops, reset_open_loop_store
from persona_ai.runtime import PersonaRuntime
from persona_ai.session.store import InMemorySessionStore
from persona_ai.web.post_call_memory import ingest_post_call_memory


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


def test_ingest_episodic_from_summary(memory_db):
    runtime = PersonaRuntime(session_store=InMemorySessionStore())
    sid = "call-1"
    session = runtime.session_store.load(sid)
    if session is None:
        from persona_ai.session.models import SessionState

        session = SessionState.new(sid)
    session.messages.append(Message.from_text("user", "Minggu depan sa mo beli motor"))
    runtime.session_store.save(session)

    payload = {
        "data": {
            "call_summary": "Ko cerita rencana beli motor minggu depan.",
            "call_successful": True,
            "user_sentiment": "neutral",
        }
    }
    counts = ingest_post_call_memory(runtime, sid, payload)
    assert counts["episodic"] == 1
    assert counts["open_loops"] == 0
    assert len(list_memories()) == 1
    assert list_pending_open_loops() == []


def test_ingest_llm_user_memories(memory_db):
    runtime = PersonaRuntime(session_store=InMemorySessionStore())
    sid = "call-3"
    payload = {
        "data": {
            "call_summary": "Ko cerita tentang pekerjaan.",
            "call_successful": True,
            "user_sentiment": "neutral",
            "user_memories": [
                {
                    "content": "Ko kerja sebagai guru di SMA",
                    "memory_type": "semantic",
                    "confidence": 0.9,
                    "from_user": True,
                },
            ],
        }
    }
    counts = ingest_post_call_memory(runtime, sid, payload)
    assert counts["facts_llm"] == 1
    assert len(list_memories()) == 2
    assert any("guru" in m.content.lower() for m in list_memories())


def test_ingest_llm_open_loops(memory_db):
    runtime = PersonaRuntime(session_store=InMemorySessionStore())
    sid = "call-2"
    payload = {
        "data": {
            "call_summary": "Ngobrol santai.",
            "call_successful": True,
            "user_sentiment": "positive",
            "open_loops": [
                {
                    "topic": "motor",
                    "content": "Ko mo cari motor bekas minggu depan",
                    "time_hint": "minggu depan",
                    "from_user": True,
                }
            ],
        }
    }
    counts = ingest_post_call_memory(runtime, sid, payload)
    assert counts["open_loops_llm"] == 1
    pending = list_pending_open_loops()
    assert any("motor" in loop.topic for loop in pending)
