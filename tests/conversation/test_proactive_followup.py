"""Proactive messages from stored open loops."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from persona_ai.conversation.proactive_followup import message_from_open_loop
from persona_ai.memory.engine import reset_memory_store
from persona_ai.memory.open_loop_engine import create_open_loop, reset_open_loop_store
from persona_ai.memory.open_loop_extract import OpenLoopCandidate
from persona_ai.memory.open_loop_models import OpenLoopRecord


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


def test_message_uses_stored_content(memory_db):
    create_open_loop(
        OpenLoopCandidate(
            topic="motor",
            content="Minggu depan sa mo beli motor bekas di Jayapura",
            time_hint="minggu depan",
            confidence=0.9,
        ),
    )
    loop = OpenLoopRecord(
        topic="motor",
        content="Minggu depan sa mo beli motor bekas di Jayapura",
        time_hint="minggu depan",
    )
    msg = message_from_open_loop(loop, language="id")
    assert "motor bekas" in msg
    assert "minggu depan" in msg
