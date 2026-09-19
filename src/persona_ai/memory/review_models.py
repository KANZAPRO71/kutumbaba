"""Memory awaiting user confirmation before entering long-term store."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from persona_ai.memory.models import DEFAULT_USER_ID, MemoryType

ReviewMemoryType = Literal["semantic", "preference", "relationship"]


class MemoryReviewRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str = DEFAULT_USER_ID
    content: str
    memory_type: ReviewMemoryType = "semantic"
    confidence: float = 0.8
    session_id: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryReviewRecord:
        return cls.model_validate(data)
