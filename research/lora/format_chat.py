"""Template percakapan bersama — lokal (char-level) dan HF/Colab."""

from __future__ import annotations

USER_TAG = "### User"
ASSIST_TAG = "### Papua"

SYSTEM_PROMPT = (
    "Kamu Papua AI, teman ngobrol Melayu Papua urban. "
    "Pakai sa/ko, kitong/tong, tra/su, mo, toh, kah, eee. "
    "Jangan pakai beta (Ambon), gue/lu, atau bahasa formal kaku."
)


def render_example(instruction: str, output: str, *, include_system: bool = False) -> str:
    parts: list[str] = []
    if include_system:
        parts.append(f"### System\n{SYSTEM_PROMPT}")
    parts.append(f"{USER_TAG}\n{instruction.strip()}")
    parts.append(f"{ASSIST_TAG}\n{output.strip()}")
    return "\n".join(parts) + "\n"


def render_prompt(instruction: str, *, include_system: bool = False) -> str:
    """Prompt untuk generate — berhenti sebelum jawaban."""
    parts: list[str] = []
    if include_system:
        parts.append(f"### System\n{SYSTEM_PROMPT}")
    parts.append(f"{USER_TAG}\n{instruction.strip()}")
    parts.append(f"{ASSIST_TAG}\n")
    return "\n".join(parts)
