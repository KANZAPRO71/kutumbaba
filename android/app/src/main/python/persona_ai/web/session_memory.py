"""Session memory for Gemini Live — richer recap across turns and calls."""

from __future__ import annotations

from persona_ai.core.types import Message
from persona_ai.memory.engine import format_memory_block, load_memories_for_prompt
from persona_ai.memory.models import UserMemoryRecord

RECENT_VERBATIM_TURNS = 14
OLDER_DIGEST_TURNS = 20
MAX_VERBATIM_CHARS = 700
MAX_DIGEST_CHARS = 200
MAX_TOTAL_TURNS = RECENT_VERBATIM_TURNS + OLDER_DIGEST_TURNS


def collapse_history(messages: list[Message]) -> list[Message]:
    collapsed: list[Message] = []
    for msg in messages:
        text = (msg.text or "").strip()
        if not text:
            continue
        if (
            collapsed
            and collapsed[-1].role == msg.role
            and msg.role in {"user", "assistant"}
        ):
            prev = collapsed[-1].text.strip()
            if text.startswith(prev) or prev.startswith(text):
                if len(text) >= len(prev):
                    collapsed[-1] = msg
                continue
        collapsed.append(msg)
    return collapsed


def _trim(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def post_call_summary(post_call: dict | None) -> str | None:
    if not isinstance(post_call, dict):
        return None
    data = post_call.get("data")
    if not isinstance(data, dict):
        return None
    for key in ("call_summary", "summary", "ringkasan"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def memory_rules_lines(*, dialect: str | None = None) -> list[str]:
    papua = dialect and dialect.strip().lower() in {"papua", "papuan", "logat_papua", "papua_id"}
    if papua:
        return [
            "Konteks obrolan (internal — jangan bacakan ke user):",
            "- Lanjutkan natural dari riwayat di bawah; jawab konsisten kalau topik sama.",
            "- Jangan sebut 'ingatan', 'daftar', atau konfirmasi 'siap ingat'.",
        ]
    return [
        "Conversation context (internal — do not read aloud):",
        "- Continue naturally from the transcript below; stay consistent when topics repeat.",
        "- Do not mention memory lists or say you will remember unless the user asks.",
    ]


def format_user_memory_block(
    user_memories: list[UserMemoryRecord] | None = None,
    *,
    dialect: str | None = None,
) -> str:
    records = user_memories if user_memories is not None else load_memories_for_prompt()
    return format_memory_block(records, dialect=dialect)


def _summary_in_user_memories(
    summary: str,
    user_memories: list[UserMemoryRecord] | None,
) -> bool:
    needle = summary.strip().lower()
    if len(needle) < 8:
        return False
    needle_words = {w for w in needle.split() if len(w) > 3}
    for record in user_memories or []:
        existing = (record.content or "").strip().lower()
        if not existing:
            continue
        if needle in existing or existing in needle:
            return True
        if not needle_words:
            continue
        existing_words = {w for w in existing.split() if len(w) > 3}
        if not existing_words:
            continue
        overlap = len(needle_words & existing_words) / min(len(needle_words), len(existing_words))
        if overlap >= 0.55:
            return True
    return False


def format_live_history_block(
    messages: list[Message] | None,
    *,
    post_call: dict | None = None,
    dialect: str | None = None,
    user_memories: list[UserMemoryRecord] | None = None,
    include_user_memory: bool = False,
) -> str:
    """Two-tier recap: older digest + recent verbatim turns."""
    user_block = (
        format_user_memory_block(user_memories, dialect=dialect)
        if include_user_memory
        else ""
    )
    summary = post_call_summary(post_call)
    if summary and _summary_in_user_memories(summary, user_memories):
        summary = None
    if not messages and not summary and not user_block:
        return ""

    lines: list[str] = []
    if user_block:
        lines.append(user_block)
        lines.append("")
    lines.extend(memory_rules_lines(dialect=dialect))

    if summary:
        lines.append(f"Ringkasan panggilan sebelumnya: {_trim(summary, 500)}")

    collapsed = collapse_history(list(messages or []))
    if not collapsed:
        return "\n".join(lines)

    total = len(collapsed)
    lines.append(f"Total {total} giliran tersimpan di sesi ini.")

    if total > RECENT_VERBATIM_TURNS:
        older = collapsed[: -RECENT_VERBATIM_TURNS][-OLDER_DIGEST_TURNS:]
        if older:
            lines.append("Ringkasan awal (jangan lupa konteks):")
            for msg in older:
                label = "Ko" if msg.role == "user" else "Sa"
                lines.append(f"  · {label}: {_trim(msg.text or '', MAX_DIGEST_CHARS)}")

    recent = collapsed[-RECENT_VERBATIM_TURNS:]
    lines.append("Percakapan terbaru (lanjutkan dari sini):")
    for msg in recent:
        label = "Ko" if msg.role == "user" else "Sa"
        lines.append(f"{label}: {_trim(msg.text or '', MAX_VERBATIM_CHARS)}")

    return "\n".join(lines)


def live_memory_steer_text(
    messages: list[Message] | None,
    *,
    post_call: dict | None = None,
    dialect: str | None = None,
    user_memories: list[UserMemoryRecord] | None = None,
) -> str | None:
    """Mid-call text refresh disabled — injecting recap after turn_complete makes Gemini speak twice."""
    return None
