"""Local companion prefs + session feedback."""

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
def prefs_db(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        from persona_ai.conversation.companion_prefs import reset_companion_prefs_store
        from persona_ai.memory.gatekeeper import min_rag_score, rag_enabled

        reset_companion_prefs_store()
        yield db_path
        reset_companion_prefs_store()


def test_patch_with_reindex_flag(client, prefs_db):
    from persona_ai.memory.engine import add_memory

    add_memory("Ko kerja di pelabuhan", memory_type="semantic")
    res = client.patch(
        "/api/companion/prefs",
        json={"rag_min_score": 0.2, "reindex_embeddings": True},
    )
    assert res.status_code == 200
    assert res.json()["reindex"]["memories"] >= 1


def test_patch_prefs_updates_gatekeeper(client, prefs_db):
    res = client.patch(
        "/api/companion/prefs",
        json={"rag_min_score": 0.32, "rag_enabled": False},
    )
    assert res.status_code == 200
    from persona_ai.memory.gatekeeper import min_rag_score, rag_enabled

    assert min_rag_score() == pytest.approx(0.32)
    assert rag_enabled() is False


def test_session_feedback_summary(client, prefs_db):
    res = client.post(
        "/api/companion/session-feedback",
        json={"session_id": "s1", "rating": "up"},
    )
    assert res.status_code == 200
    assert res.json()["summary"]["up"] == 1
    stats = client.get("/api/companion/stats").json()
    assert stats["stats"]["session_feedback"]["up"] == 1
