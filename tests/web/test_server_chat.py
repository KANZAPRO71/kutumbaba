"""Tests for Persona Chat HTTP server."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    import persona_ai.web.server as server_mod

    importlib.reload(server_mod)
    return TestClient(server_mod.app)


def test_time_question_bypasses_llm(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    server = importlib.import_module("persona_ai.web.server")
    importlib.reload(server)

    response = server.chat(
        server.ChatRequest(session_id="clock-test", message="Sekarang jam berapa?")
    )

    assert response.llm_called is False
    assert response.execution_profile == "clock"
    assert response.raw_bdv == "RESPOND"
    assert response.effective_bdv == "RESPOND"
    assert "UTC" in (response.text or "")


def test_session_history_without_gemini_key(monkeypatch):
    monkeypatch.setattr("persona_ai.web.server.load_project_dotenv", lambda: None)
    import persona_ai.web.server as server_mod

    importlib.reload(server_mod)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = TestClient(server_mod.app)
    res = client.get("/api/session/web-57c1d77a")
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] == "web-57c1d77a"
    assert data["messages"] == []


def test_health_degraded_without_key(monkeypatch):
    monkeypatch.setattr("persona_ai.web.server.load_project_dotenv", lambda: None)
    import persona_ai.web.server as server_mod

    importlib.reload(server_mod)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = TestClient(server_mod.app)
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("degraded", "starting")
    assert data["gemini_key_set"] is False


def test_retell_turn_requires_transcript(client):
    res = client.post("/api/retell/turn", json={"session_id": "call-1"})
    assert res.status_code == 400


def test_retell_turn_routes_to_persona(client):
    res = client.post(
        "/api/retell/turn",
        json={
            "call_id": "call-99",
            "transcript": "Oke",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "response_type" in data
    assert "bdv_action" in data
