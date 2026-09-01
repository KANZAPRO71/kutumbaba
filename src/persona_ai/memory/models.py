"""User memory record — facts stored locally on the user's device."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

MemoryType = Literal["semantic", "preference", "episodic", "manual"]
MemorySource = Literal["user_explicit", "post_call", "manual", "inferred"]

DEFAULT_USER_ID = "local"


class UserMemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str = DEFAULT_USER_ID
    memory_type: MemoryType = "semantic"
    content: str
    confidence: float = 0.9
    source: MemorySource = "manual"
    session_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def touch(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        self.updated_at = now

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserMemoryRecord:
        return cls.model_validate(data)
