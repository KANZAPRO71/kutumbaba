"""Tests for user memory store and extraction."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from persona_ai.memory.engine import (
    add_memory,
    commit_episodic,
    commit_from_text,
    delete_memory,
    format_memory_block,
    list_memories,
)
from persona_ai.memory.extract import extract_memory_candidates
from persona_ai.memory.store import SQLiteUserMemoryStore


@pytest.fixture
def memory_db(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        from persona_ai.memory.engine import reset_memory_store

        reset_memory_store()
        yield db_path
        reset_memory_store()


def test_extract_explicit_remember():
    candidates = extract_memory_candidates("Ingat ya, nama ko Budi suka basket")
    assert len(candidates) == 1
    assert "Budi" in candidates[0].content
    assert candidates[0].memory_type == "semantic"


def test_extract_preference():
    candidates = extract_memory_candidates("Ko tra suka pedas banget")
    assert len(candidates) == 1
    assert candidates[0].memory_type == "preference"


def test_vent_not_extracted():
    candidates = extract_memory_candidates("Ah capek banget hari ini")
    assert candidates == []


def test_store_save_and_list(memory_db):
    record = add_memory("Nama ko Budi", memory_type="manual", source="manual")
    assert record is not None
    items = list_memories()
    assert len(items) == 1
    assert items[0].content == "Nama ko Budi"


def test_commit_from_text(memory_db):
    saved = commit_from_text("Ingat dong, ko alergi seafood", session_id="s1")
    assert len(saved) == 1
    assert "seafood" in saved[0].content.lower()


def test_dedupe_similar(memory_db):
    add_memory("Nama ko Budi", memory_type="manual")
    add_memory("Nama ko Budi", memory_type="manual")
    assert len(list_memories()) == 1


def test_delete_memory(memory_db):
    record = add_memory("Test hapus", memory_type="manual")
    assert record is not None
    assert delete_memory(record.id)
    assert list_memories() == []


def test_commit_episodic(memory_db):
    record = commit_episodic("Ngobrol tentang pekerjaan dan rencana liburan", session_id="s2")
    assert record is not None
    assert record.memory_type == "episodic"


def test_format_memory_block_papua(memory_db):
    add_memory("Nama ko Budi", memory_type="semantic")
    block = format_memory_block(list_memories(), dialect="papua")
    assert "INGATAN KHUSUS KO" in block
    assert "Budi" in block


def test_sqlite_store_direct():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        store = SQLiteUserMemoryStore(Path(tmp) / "mem.db")
        from persona_ai.memory.models import UserMemoryRecord

        rec = UserMemoryRecord(content="Test direct")
        store.save(rec)
        assert store.count() == 1
        assert store.get(rec.id) is not None
        store.close()
