"""In-memory arc store — v0 minimal."""

from __future__ import annotations

from persona_ai.core.types import ConversationArc

_store: dict[str, ConversationArc] = {}


def load(session_id: str) -> ConversationArc:
    if session_id not in _store:
        _store[session_id] = ConversationArc(session_id=session_id)
    return _store[session_id].model_copy(deep=True)


def save(arc: ConversationArc) -> None:
    _store[arc.session_id] = arc.model_copy(deep=True)


def reset() -> None:
    _store.clear()
