"""Pytest hooks — stub Gemini in unit tests; live_gemini marker uses real API."""

from __future__ import annotations

from pathlib import Path

import pytest


_DEFAULT_ADAPTER_MODULES = (
    "persona_ai.llm.adapter",
    "persona_ai.runtime",
    "persona_ai.sim.drift_harness",
    "persona_ai.sim.smoke_openai",
    "persona_ai.eval.ab_experiment",
    "persona_ai.integrations.gemini_direct",
    "persona_ai.integrations.persona_eval",
    "persona_ai.integrations.retell_webhook",
)


@pytest.fixture(autouse=True)
def _isolate_session_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "persona_sessions.db"
    monkeypatch.setenv("PERSONA_SESSION_DB", str(db))


@pytest.fixture(autouse=True)
def _stub_default_llm(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live_gemini"):
        return

    from tests.support.stub_llm import StubLLMAdapter

    stub = StubLLMAdapter()
    import persona_ai.llm.adapter as adapter_mod

    def patched_default_adapter():
        return stub

    def patched_get_adapter(name: str = "gemini"):
        if name == "openai":
            return adapter_mod.OpenAILLMAdapter()
        return stub

    for module in _DEFAULT_ADAPTER_MODULES:
        monkeypatch.setattr(f"{module}.default_adapter", patched_default_adapter)

    monkeypatch.setattr(adapter_mod, "get_adapter", patched_get_adapter)
    monkeypatch.setattr("persona_ai.sim.smoke_openai.get_adapter", patched_get_adapter)

    # Reset pipeline singleton so prior tests do not leak adapter choice.
    import persona_ai.conversation.pipeline_v0 as pipeline_v0

    monkeypatch.setattr(pipeline_v0, "_compat_runtime", None)
