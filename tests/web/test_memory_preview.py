"""Memory RAG preview + health config."""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("PERSONA_MEMORY_RAG", "1")
    import persona_ai.web.server as server_mod

    importlib.reload(server_mod)
    return TestClient(server_mod.app)


def test_health_includes_memory_rag(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    rag = res.json().get("memory_rag")
    assert rag is not None
    assert rag["enabled"] is True
    assert "min_score" in rag


def test_memory_preview_empty(client, monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        from persona_ai.memory.engine import reset_memory_store
        from persona_ai.memory.embedding_store import reset_embedding_store
        from persona_ai.memory.open_loop_engine import reset_open_loop_store

        reset_memory_store()
        reset_open_loop_store()
        reset_embedding_store()

        res = client.get("/api/companion/memory-preview", params={"query": "motor"})
        assert res.status_code == 200
        data = res.json()
        assert data["retrieval_mode"] in ("semantic", "semantic_empty", "recency")
