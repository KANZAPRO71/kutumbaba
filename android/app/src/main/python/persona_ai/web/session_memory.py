"""Session memory for Gemini Live — richer recap across turns and calls."""

from __future__ import annotations

from persona_ai.core.types import Message
from persona_ai.memory.engine import format_memory_block, load_memories_for_prompt
from persona_ai.memory.models import UserMemoryRecord
from persona_ai.memory.open_loop_engine import format_open_loops_block
from persona_ai.memory.open_loop_models import OpenLoopRecord
from persona_ai.memory.retrieve import CompanionMemoryContext, retrieve_companion_memory

RECENT_VERBATIM_TURNS = 14
NATURAL_RECENT_VERBATIM_TURNS = 4
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
            "- Riwayat di bawah untuk konteks — variasi natural, jangan ulang kalimat persis.",
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


def _last_user_line(messages: list[Message] | None) -> str:
    if not messages:
        return ""
    for msg in reversed(messages):
        if msg.role == "user":
            text = (msg.text or "").strip()
            if text:
                return text
    return ""


def load_companion_context_for_turn(
    query: str | None = None,
    *,
    messages: list[Message] | None = None,
) -> CompanionMemoryContext:
    from persona_ai.memory.live_policy import apply_live_memory_policy

    effective = (query or _last_user_line(messages)).strip()
    ctx = retrieve_companion_memory(effective or None)
    return apply_live_memory_policy(ctx)


def format_companion_context_block(
    ctx: CompanionMemoryContext,
    *,
    dialect: str | None = None,
) -> str:
    from persona_ai.memory.live_policy import apply_live_memory_policy, live_memory_mention_rules

    ctx = apply_live_memory_policy(ctx)
    if not ctx.user_memories and not ctx.open_loops:
        return ""
    parts: list[str] = [live_memory_mention_rules(dialect=dialect)]
    if ctx.user_memories:
        parts.append(format_memory_block(list(ctx.user_memories), dialect=dialect))
    if ctx.open_loops:
        parts.append(format_open_loops_block(list(ctx.open_loops), dialect=dialect))
    return "\n\n".join(part for part in parts if part)


def _summary_in_user_memories(
    summary: str,
    user_memories: list[UserMemoryRecord] | None,
) -> bool:
    cleaned = " ".join((summary or "").split()).strip()
    if len(cleaned) < 8:
        return False
    from persona_ai.memory.embedding_index import embed_query, vector_for_memory
    from persona_ai.memory.vector_math import cosine_similarity

    q_vec = embed_query(cleaned)
    for record in user_memories or []:
        if cosine_similarity(q_vec, vector_for_memory(record)) >= 0.55:
            return True
    return False


def format_live_history_block(
    messages: list[Message] | None,
    *,
    post_call: dict | None = None,
    dialect: str | None = None,
    user_memories: list[UserMemoryRecord] | None = None,
    include_user_memory: bool = False,
    open_loops: list[OpenLoopRecord] | None = None,
    include_open_loops: bool = False,
    include_companion_memory: bool = False,
    companion_query: str | None = None,
    recent_verbatim_turns: int | None = None,
    filter_filler_loops: bool = False,
) -> str:
    """Two-tier recap: older digest + recent verbatim turns."""
    from persona_ai.personality.papua_dialect_phrases import is_papua_dialect
    from persona_ai.personality.papua_loop_guard import should_omit_assistant_from_recap

    recent_cap = recent_verbatim_turns if recent_verbatim_turns is not None else RECENT_VERBATIM_TURNS
    recent_cap = max(2, min(recent_cap, RECENT_VERBATIM_TURNS))
    papua = is_papua_dialect(dialect)
    skip_filler = filter_filler_loops and papua

    ctx: CompanionMemoryContext | None = None
    if include_companion_memory:
        ctx = load_companion_context_for_turn(companion_query, messages=messages)
        include_user_memory = include_user_memory or bool(ctx.user_memories)
        include_open_loops = include_open_loops or bool(ctx.open_loops)
        if user_memories is None and ctx.user_memories:
            user_memories = list(ctx.user_memories)
        if open_loops is None and ctx.open_loops:
            open_loops = list(ctx.open_loops)

    user_block = (
        format_user_memory_block(user_memories, dialect=dialect)
        if include_user_memory and user_memories
        else ""
    )
    loop_block = (
        format_open_loops_block(open_loops, dialect=dialect)
        if include_open_loops and open_loops
        else ""
    )
    summary = post_call_summary(post_call)
    if summary and _summary_in_user_memories(summary, user_memories):
        summary = None
    if not messages and not summary and not user_block and not loop_block:
        return ""

    lines: list[str] = []
    if user_block:
        lines.append(user_block)
        lines.append("")
    if loop_block:
        lines.append(loop_block)
        lines.append("")
    lines.extend(memory_rules_lines(dialect=dialect))

    if summary:
        lines.append(f"Ringkasan panggilan sebelumnya: {_trim(summary, 500)}")

    collapsed = collapse_history(list(messages or []))
    if not collapsed:
        return "\n".join(lines)

    total = len(collapsed)
    lines.append(f"Total {total} giliran tersimpan di sesi ini.")

    if total > recent_cap:
        older = collapsed[: -recent_cap][-OLDER_DIGEST_TURNS:]
        if older:
            lines.append("Ringkasan awal (jangan lupa konteks):")
            for msg in older:
                if skip_filler and msg.role == "assistant" and should_omit_assistant_from_recap(msg.text or ""):
                    continue
                label = "Ko" if msg.role == "user" else "Sa"
                lines.append(f"  · {label}: {_trim(msg.text or '', MAX_DIGEST_CHARS)}")

    recent = collapsed[-recent_cap:]
    lines.append("Percakapan terbaru (lanjutkan dari sini):")
    recent_norms: list[str] = []
    for msg in recent:
        if skip_filler and msg.role == "assistant":
            if should_omit_assistant_from_recap(msg.text or "", recent=recent_norms):
                continue
            recent_norms.append(" ".join((msg.text or "").strip().split()).lower())
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
