"""When and how much companion memory may shape live turns — not a full DB dump."""

from __future__ import annotations

from persona_ai.memory.retrieve import CompanionMemoryContext

MAX_LIVE_USER_MEMORIES = 4
MAX_LIVE_OPEN_LOOPS = 2


def apply_live_memory_policy(ctx: CompanionMemoryContext) -> CompanionMemoryContext:
    """Drop irrelevant RAG misses; cap rows injected into Gemini."""
    if ctx.retrieval_mode == "semantic_empty" and not ctx.open_loops:
        return CompanionMemoryContext(
            user_memories=(),
            open_loops=(),
            query=ctx.query,
            retrieval_mode=ctx.retrieval_mode,
        )
    memories = ctx.user_memories[:MAX_LIVE_USER_MEMORIES]
    loops = ctx.open_loops[:MAX_LIVE_OPEN_LOOPS]
    return CompanionMemoryContext(
        user_memories=memories,
        open_loops=loops,
        query=ctx.query,
        retrieval_mode=ctx.retrieval_mode,
    )


def live_memory_mention_rules(*, dialect: str | None = None) -> str:
    papua = dialect and dialect.strip().lower() in {"papua", "papuan", "logat_papua", "papua_id"}
    if papua:
        return (
            "ATURAN INGATAN LIVE (internal):\n"
            "- Pakai ingatan hanya kalau ko barusan bahas topik itu atau ko tanya langsung.\n"
            "- Jangan sebut ingatan random di awal/topik baru; jangan bacakan daftar.\n"
            "- Open loop: follow-up natural satu kalimat — bukan 'ingat ya dulu ko bilang…' panjang.\n"
            "- Kalau ragu relevansi, diam saja — obrolan normal lebih penting."
        )
    return (
        "LIVE MEMORY RULES (internal):\n"
        "- Use memory only when the user just raised that topic or asked directly.\n"
        "- Never dump the list; one natural reference max when relevant.\n"
        "- If unsure, skip memory — normal conversation wins."
    )
