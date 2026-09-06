"""Jangan tarik runtime persona_ai — tes LM CPU berdiri sendiri."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_session_db() -> None:
    return None


@pytest.fixture(autouse=True)
def _stub_default_llm() -> None:
    return None
