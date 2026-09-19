"""Proactive expression — copy/hints only; decisions live in callback_gate."""

from __future__ import annotations

from dataclasses import dataclass

from persona_ai.memory.models import DEFAULT_USER_ID
from persona_ai.memory.open_loop_engine import list_pending_open_loops
from persona_ai.memory.open_loop_models import OpenLoopRecord

_MAX_SNIPPET = 110


@dataclass(frozen=True)
class CallbackCandidate:
    loop_id: str
    topic: str
    content: str
    time_hint: str | None = None
    priority: float = 0.5
    tone: str = "natural"


def _trim_snippet(text: str, *, limit: int = _MAX_SNIPPET) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def latest_pending_open_loop(user_id: str = DEFAULT_USER_ID) -> OpenLoopRecord | None:
    pending = list_pending_open_loops(user_id, limit=1)
    return pending[0] if pending else None


def callback_expression_hint(
    candidate: CallbackCandidate,
    *,
    experience_mode: str,
    language: str = "id",
) -> str:
    """Human-facing style hint — not spoken verbatim by gate."""
    snippet = _trim_snippet(candidate.content, limit=80)
    if experience_mode == "mop":
        if language == "id":
            return f"Weh, sa belum lupa cerita itu — {snippet} 😂"
        return f"Still remember: {snippet}"
    if language == "id":
        return f"Eh, yang kemarin itu — {snippet} — jadi gimana?"
    return f"About earlier — {snippet} — how did it go?"


def callback_internal_steer(
    candidate: CallbackCandidate,
    *,
    experience_mode: str,
    language: str = "id",
) -> str:
    """Internal Live steer fragment — sambung natural setelah jawab user dulu."""
    snippet = _trim_snippet(candidate.content, limit=90)
    if language == "id":
        base = (
            f"CALLBACK (internal): urutan belum selesai — «{snippet}». "
            "Setelah reaksi singkat ke ucapan user barusan, sambung natural "
            "(bukan buka dengan 'eh kemarin' di awal turn). Satu kalimat, "
            "jangan bacakan seperti database."
        )
        if experience_mode == "mop":
            base += " Boleh playful ringan, bukan stand-up panjang."
        elif experience_mode in {"cerita_tong", "teman_malam"}:
            base += " Lembut & pendek — jangan memotong curhat user."
        return base
    return (
        f"CALLBACK (internal): open thread «{snippet}». "
        "React to the user's latest line first, then one natural follow-up."
    )


def message_from_open_loop(
    loop: OpenLoopRecord,
    *,
    language: str = "id",
) -> str:
    """Generic banner copy — avoid open-loop retrieval tone (Sprint C)."""
    _ = loop
    if language == "id":
        return "Mau ngobrol sebentar? Tekan Buka Suara kalau ko ready."
    return "Want a quick voice hangout? Tap Call when ready."


def live_hint_from_open_loop(loop: OpenLoopRecord, *, language: str = "id") -> str:
    snippet = _trim_snippet(loop.content, limit=80)
    if language == "id":
        return (
            f"Urutan belum selesai (internal): {snippet} — "
            "hanya sambung setelah user bicara; jangan buka dengan callback."
        )
    return f"Pending thread (internal): {snippet} — follow up only after user speaks."
