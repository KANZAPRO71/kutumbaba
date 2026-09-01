"""PII redaction by category — Retell Personal Info Redaction parity."""

from __future__ import annotations

import re
from typing import Iterable

_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone": re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\d{8,15}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "address": re.compile(
        r"\b\d{1,5}\s+\w+(?:\s+\w+){0,4}\s+(?:street|st|avenue|ave|road|rd|jalan|jl\.?)\b",
        re.I,
    ),
}

_REDACTED = "[REDACTED]"


def redact_text(text: str, categories: Iterable[str]) -> str:
    """Redact selected PII categories in place."""
    if not text or not categories:
        return text
    out = text
    for category in categories:
        pattern = _PII_PATTERNS.get(category)
        if pattern is not None:
            out = pattern.sub(_REDACTED, out)
    return out


def categories_for_storage_mode(storage_mode: str, *, pii_enabled: bool) -> tuple[str, ...]:
    """Default PII categories when storage mode strips sensitive content."""
    if storage_mode == "everything" and not pii_enabled:
        return ()
    if storage_mode == "basic_attributes":
        return ()
    return ("email", "phone", "credit_card", "ssn")
