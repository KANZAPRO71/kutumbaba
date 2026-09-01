"""Default v1 policy rules — minimal hard gate set."""

from __future__ import annotations

import re

# P1 — crisis keywords (tier-0 must_respond, not block)
DEFAULT_CRISIS_KEYWORDS = (
    "ingin bunuh diri",
    "mau bunuh diri",
    "want to kill myself",
    "suicide plan",
)

# Input hard-block patterns (never reach LLM)
INPUT_BLOCK_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "P5",
        re.compile(r"\b(cara|how to)\s+(membuat|make|build)\s+(bom|bomb|senjata|weapon)\b", re.I),
        "Blocked: violence instructions",
    ),
    (
        "P6",
        re.compile(r"\b(share|kirim|berikan)\s+(password|otp|pin|cvv|credit card)\b", re.I),
        "Blocked: credential harvesting",
    ),
    (
        "P7",
        re.compile(r"\b(hack|bobol)\s+(akun|account|email)\b", re.I),
        "Blocked: illegal access request",
    ),
]

# Post-check forbidden patterns
FP1_AI_DISCLAIMER = re.compile(
    r"\b(sebagai ai|as an language model|as a language model|i am an ai)\b[.,]?\s*",
    re.I,
)
FP3_CREDENTIAL_COLLECT = re.compile(
    r"\b(kirimkan|send|share|berikan)\s+(password|otp|pin|nomor kartu|credit card)\b",
    re.I,
)
FP4_DEFAULT_DENYLIST = (
    "ignore all previous instructions",
    "system prompt leak",
)

OUTPUT_BLOCK_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "S1",
        re.compile(r"\b(cara membuat bom|how to make a bomb)\b", re.I),
        "Safety: violence instructions",
    ),
]

CRISIS_RESOURCE_LINE = (
    "Jika kamu atau seseorang dalam bahaya, hubungi layanan darurat setempat "
    "atau hotline krisis yang tersedia."
)

DEFAULT_INPUT_BLOCK_FALLBACK = "Aku nggak bisa bantu itu."
DEFAULT_OUTPUT_BLOCK_FALLBACK = "Aku nggak bisa bantu itu."
