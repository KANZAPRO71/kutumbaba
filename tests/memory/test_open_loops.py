"""Tests for open-loop memory (structured create — no chat keyword rules)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from persona_ai.memory.open_loop_engine import (
    create_open_loop,
    format_open_loops_block,
    list_pending_open_loops,
    reset_open_loop_store,
    resolve_by_topic_hint,
    resolve_open_loop,
)
from persona_ai.memory.open_loop_extract import OpenLoopCandidate, extract_open_loop_candidates
from persona_ai.memory.engine import reset_memory_store


@pytest.fixture
def memory_db(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        reset_memory_store()
        reset_open_loop_store()
        yield db_path
        reset_memory_store()
        reset_open_loop_store()


def test_extract_from_chat_is_disabled():
    assert extract_open_loop_candidates("Nanti sore sa mau ke rumah mama") == []


def test_create_structured_open_loop(memory_db):
    record = create_open_loop(
        OpenLoopCandidate(
            topic="rumah-mama",
            content="Nanti sore sa mau ke rumah mama",
            time_hint="nanti sore",
            confidence=0.9,
        ),
        session_id="s1",
    )
    assert record is not None
    pending = list_pending_open_loops()
    assert len(pending) == 1
    assert pending[0].content.startswith("Nanti sore")


def test_dedupe_exact_content(memory_db):
    create_open_loop(
        OpenLoopCandidate(
            topic="pindah",
            content="Minggu depan sa pindah rumah",
            time_hint="minggu depan",
            confidence=0.9,
        ),
    )
    create_open_loop(
        OpenLoopCandidate(
            topic="pindah-rumah",
            content="Minggu depan sa pindah rumah",
            time_hint="minggu depan",
            confidence=0.95,
        ),
    )
    assert len(list_pending_open_loops()) == 1


def test_resolve_by_id(memory_db):
    record = create_open_loop(
        OpenLoopCandidate(
            topic="rapat",
            content="Lusa sa ada rapat dengan tim",
            time_hint="lusa",
            confidence=0.9,
        ),
    )
    assert record is not None
    resolved = resolve_open_loop(record.id)
    assert resolved is not None
    assert resolved.status == "resolved"
    assert list_pending_open_loops() == []


def test_resolve_by_topic_slug(memory_db):
    create_open_loop(
        OpenLoopCandidate(
            topic="motor",
            content="Minggu depan sa mo beli motor",
            time_hint=None,
            confidence=0.88,
        ),
    )
    resolved = resolve_by_topic_hint("motor")
    assert resolved is not None
    assert resolved.status == "resolved"


def test_format_block_papua(memory_db):
    create_open_loop(
        OpenLoopCandidate(
            topic="rapat",
            content="Lusa sa ada rapat dengan tim",
            time_hint="lusa",
            confidence=0.9,
        ),
    )
    block = format_open_loops_block(list_pending_open_loops(), dialect="papua")
    assert "URUSAN BELUM SELESAI" in block
    assert "rapat" in block.lower()
