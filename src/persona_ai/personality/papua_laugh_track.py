"""Laugh track (audience applause) — trigger after Raja Mop punchline on turn_complete."""

from __future__ import annotations

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect
from persona_ai.personality.papua_mops import _humor_query

_PUNCHLINE_MARKERS = (
    "obet",
    "tinus",
    "pace satu",
    "mace satu",
    "komandan",
    "ibu guru",
    "penjual",
    "sopir",
    "ketua rt",
    "pocong",
    "ondoafi",
)


def _assistant_delivered_mop_punchline(text: str) -> bool:
    """Laugh track hanya setelah cerita mop/punchline — bukan obrolan pendek."""
    t = text.strip()
    if len(t) < 80:
        return False
    lower = t.lower()
    if "..." in t:
        return True
    if any(m in lower for m in _PUNCHLINE_MARKERS):
        return True
    return _humor_query(t) and len(t) >= 120


def mark_humor_turn(gov: dict, user_text: str) -> None:
    """Tandai giliran mop/humor dari transkrip user."""
    if _humor_query(user_text):
        gov["laugh_track_pending"] = True


def should_play_laugh_track(gov: dict, dialect: str | None) -> bool:
    """Putar laugh penonton cuma setelah punchline mop selesai — bukan tiap obrolan."""
    if not is_papua_dialect(dialect):
        return False
    assistant = (gov.get("assistant_text") or "").strip()
    if not assistant or not _assistant_delivered_mop_punchline(assistant):
        return False
    gov["laugh_track_pending"] = False
    return True


def should_play_jedag_jedug(gov: dict, dialect: str | None) -> bool:
    """Jedag-jedug burst 3 detik — sama trigger dengan laugh track punchline."""
    return should_play_laugh_track(gov, dialect)
