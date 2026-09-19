"""Embedding reindex after prefs / manual refresh."""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    import persona_ai.web.server as server_mod

    importlib.reload(server_mod)
    return TestClient(server_mod.app)


@pytest.fixture
def memory_db(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        from persona_ai.conversation.companion_prefs import reset_companion_prefs_store
        from persona_ai.memory.engine import add_memory, reset_memory_store
        from persona_ai.memory.embedding_store import get_embedding_store, reset_embedding_store
        from persona_ai.memory.open_loop_engine import reset_open_loop_store

        reset_memory_store()
        reset_open_loop_store()
        reset_embedding_store()
        reset_companion_prefs_store()
        add_memory("Ko suka reggae", memory_type="preference")
        yield
        reset_memory_store()
        reset_open_loop_store()
        reset_embedding_store()
        reset_companion_prefs_store()


def test_reindex_endpoint(client, memory_db):
    res = client.post("/api/memory/reindex-embeddings")
    assert res.status_code == 200
    body = res.json()
    assert body["reindexed"]["memories"] >= 1


def test_toggle_gemini_triggers_reindex(client, memory_db):
    res = client.patch("/api/companion/prefs", json={"rag_use_gemini": True})
    assert res.status_code == 200
    assert res.json().get("reindex") is not None
    from persona_ai.memory.embedding_store import get_embedding_store

    mem_id = client.get("/api/memory").json()["memories"][0]["id"]
    vec = get_embedding_store().get("memory", mem_id)
    assert vec is not None
