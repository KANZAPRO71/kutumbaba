"""Session state models — v1 text MVP."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from persona_ai.coherence.bind import IdentityAnchor
from persona_ai.core.types import ConversationArc, Message, TurnHistory

SESSION_SCHEMA_VERSION = "session_v1"


class SessionState(BaseModel):
    """Persisted multi-turn session — only runtime-required fields."""

    schema_version: str = SESSION_SCHEMA_VERSION
    session_id: str
    messages: list[Message] = Field(default_factory=list)
    arc: ConversationArc
    anchor: IdentityAnchor = Field(default_factory=IdentityAnchor)
    turn_history: TurnHistory = Field(default_factory=TurnHistory)
    turn_index: int = 0
    post_call: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def new(cls, session_id: str, *, profile_warmth: float = 0.6) -> SessionState:
        now = _utc_now()
        return cls(
            session_id=session_id,
            arc=ConversationArc(
                session_id=session_id,
                relational_warmth=max(0.25, profile_warmth - 0.05),
            ),
            anchor=IdentityAnchor(session_tone_baseline=profile_warmth),
            created_at=now,
            updated_at=now,
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize_session(state: SessionState) -> dict[str, Any]:
    return state.model_dump(mode="json")


def deserialize_session(data: dict[str, Any]) -> SessionState:
    """Load session from storage; fail clearly on invalid required fields."""
    if not isinstance(data, dict):
        raise ValueError("session payload must be a JSON object")
    version = data.get("schema_version")
    if version is None:
        raise ValueError("session payload missing required field: schema_version")
    if version != SESSION_SCHEMA_VERSION:
        raise ValueError(f"unsupported session schema_version: {version!r}")
    if not data.get("session_id"):
        raise ValueError("session payload missing required field: session_id")
    try:
        return SessionState.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"invalid session payload: {exc}") from exc
