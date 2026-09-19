"""Import memory export v2/v3."""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from persona_ai.memory.engine import export_user_data, list_memories, reset_memory_store
from persona_ai.memory.import_restore import import_user_data
from persona_ai.memory.open_loop_engine import list_pending_open_loops, reset_open_loop_store


@pytest.fixture
def memory_db(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        from persona_ai.conversation.companion_prefs import reset_companion_prefs_store
        from persona_ai.memory.embedding_store import reset_embedding_store
        from persona_ai.memory.review_engine import reset_review_store

        reset_memory_store()
        reset_open_loop_store()
        reset_embedding_store()
        reset_review_store()
        reset_companion_prefs_store()
        yield
        reset_memory_store()
        reset_open_loop_store()
        reset_embedding_store()
        reset_review_store()
        reset_companion_prefs_store()


def test_merge_skips_duplicate_content(memory_db):
    from persona_ai.memory.engine import add_memory

    add_memory("Nama ko Budi", memory_type="manual")
    exported = export_user_data()
    counts = import_user_data(exported, mode="merge")
    assert counts["memories"] == 0


def test_replace_restores_export(memory_db):
    from persona_ai.memory.engine import add_memory

    add_memory("Nama ko Obet", memory_type="manual")
    exported = export_user_data()
    add_memory("Nama ko Zeta", memory_type="manual")
    counts = import_user_data(exported, mode="replace")
    assert counts["memories"] >= 1
    contents = {m.content for m in list_memories()}
    assert any("Obet" in c for c in contents)
    assert not any("Zeta" in c for c in contents)


@pytest.fixture
def api_client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    import persona_ai.web.server as server_mod

    importlib.reload(server_mod)
    return TestClient(server_mod.app)


def test_import_api(api_client, memory_db):
    payload = export_user_data()
    res = api_client.post("/api/memory/import", json={"payload": payload, "mode": "merge"})
    assert res.status_code == 200
    assert res.json()["ok"] is True
