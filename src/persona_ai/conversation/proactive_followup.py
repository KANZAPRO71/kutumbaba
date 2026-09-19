"""Proactive companion copy from stored data — not keyword templates."""

from __future__ import annotations

from persona_ai.memory.models import DEFAULT_USER_ID
from persona_ai.memory.open_loop_engine import list_pending_open_loops
from persona_ai.memory.open_loop_models import OpenLoopRecord

_MAX_SNIPPET = 110


def _trim_snippet(text: str, *, limit: int = _MAX_SNIPPET) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def latest_pending_open_loop(user_id: str = DEFAULT_USER_ID) -> OpenLoopRecord | None:
    pending = list_pending_open_loops(user_id, limit=1)
    return pending[0] if pending else None


def message_from_open_loop(
    loop: OpenLoopRecord,
    *,
    language: str = "id",
) -> str:
    snippet = _trim_snippet(loop.content)
    hint = (loop.time_hint or "").strip()
    if language == "id":
        time_part = f" ({hint})" if hint else ""
        return (
            f"Ko pernah bilang{time_part}: «{snippet}». "
            "Mau lanjut cerita? Tekan Ngobrol."
        )
    time_part = f" ({hint})" if hint else ""
    return f'You said{time_part}: "{snippet}". Want to pick that up? Tap Call.'


def live_hint_from_open_loop(loop: OpenLoopRecord, *, language: str = "id") -> str:
    snippet = _trim_snippet(loop.content, limit=80)
    if language == "id":
        return (
            f"Urutan belum selesai (internal): {snippet} — "
            "sambung natural kalau ko buka obrolan; jangan bacakan seperti daftar."
        )
    return (
        f"Pending thread (internal): {snippet} — follow up naturally if they open chat."
    )
