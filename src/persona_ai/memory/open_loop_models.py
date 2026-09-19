"""Open-loop records — conversational threads left unfinished."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from persona_ai.memory.models import DEFAULT_USER_ID, OpenLoopStatus

OpenLoopSource = Literal["inferred", "user_explicit", "manual"]


class OpenLoopRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str = DEFAULT_USER_ID
    topic: str
    content: str
    status: OpenLoopStatus = "pending"
    time_hint: str | None = None
    source: OpenLoopSource = "inferred"
    session_id: str | None = None
    confidence: float = 0.8
    created_at: str = ""
    updated_at: str = ""
    resolved_at: str | None = None

    def touch(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        self.updated_at = now

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenLoopRecord:
        return cls.model_validate(data)
