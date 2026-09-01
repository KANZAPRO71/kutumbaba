"""Policy types — v1 hard gate only."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from persona_ai.core.types import PolicySignal


class PolicyStatus(str, Enum):
    APPROVED = "APPROVED"
    REWRITE = "REWRITE"
    BLOCK = "BLOCK"


class PiiHandling(str, Enum):
    REDACT = "redact"
    REFUSE = "refuse"
    ALLOW = "allow"


class SensitiveDepth(str, Enum):
    NONE = "none"
    LOW = "low"
    STANDARD = "standard"


class PolicyViolation(BaseModel):
    rule_id: str
    category: str
    detail: str = ""


class PolicyConstraints(BaseModel):
    required_disclaimer: str | None = None
    blocked_topics: list[str] = Field(default_factory=list)
    blocked_phrases: list[str] = Field(default_factory=list)
    pii_handling: PiiHandling = PiiHandling.ALLOW
    max_sensitive_depth: SensitiveDepth = SensitiveDepth.STANDARD
    inject_system_lines: list[str] = Field(default_factory=list)
    tier0_signals: list[PolicySignal] = Field(default_factory=list)
    input_blocked: bool = False
    block_reason: str | None = None
    fallback_text: str | None = None


class PolicyPreCheckResult(BaseModel):
    constraints: PolicyConstraints
    tier0_signals: list[PolicySignal] = Field(default_factory=list)
    input_blocked: bool = False
    block_reason: str | None = None
    fallback_text: str | None = None


class PolicyResult(BaseModel):
    status: PolicyStatus
    violations: list[PolicyViolation] = Field(default_factory=list)
    rewrite_hint: str | None = None
    preserve_voice_register: bool = True
    final_text: str | None = None
    rewrite_count: int = 0


class PolicyContext(BaseModel):
    """Minimal v1 policy configuration — session/persona scoped."""

    crisis_keywords: list[str] = Field(default_factory=list)
    regulated_domain: bool = False
    required_disclaimer: str | None = None
    phrase_denylist: list[str] = Field(default_factory=list)
    slur_denylist: list[str] = Field(default_factory=list)
    pii_mode: PiiHandling = PiiHandling.ALLOW
