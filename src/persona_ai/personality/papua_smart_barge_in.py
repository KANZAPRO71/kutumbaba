"""Smart barge-in — jangan potong AI cuma karena batuk atau 'Iyo' pendek."""

from __future__ import annotations

import re
import time

MIN_CHALLENGE_DURATION_S = 0.8

_FILLER_ONLY = frozenset({
    "iyo", "iya", "ah", "eh", "em", "ehem", "hem", "oh", "uh", "um",
    "hmm", "hm", "ee", "eee", "toh", "kah", "mo", "su",
})

_CHALLENGE_PHRASES = (
    "ko tipu",
    "ko bohong",
    "stop sudah",
    "sudah cukup",
    "ganti mop",
    "tra lucu",
    "tra percaya",
    "bohong",
    "tipu sa",
    "diam sudah",
    "potong cerita",
    "ganti cerita",
    "mop lain",
    "mop baru",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def is_filler_only(text: str | None) -> bool:
    """Suara/ucapan pendek non-penantang — jangan potong AI."""
    if not text or not text.strip():
        return True
    q = _normalize(text)
    if not q:
        return True
    words = [w for w in re.split(r"[^\w']+", q) if w]
    if not words:
        return True
    if len(words) == 1 and words[0] in _FILLER_ONLY:
        return True
    if len(q) <= 4 and q in _FILLER_ONLY:
        return True
    return False


def is_challenge_interrupt(text: str | None) -> bool:
    """Interupsi penantang yang jelas — boleh potong AI."""
    if not text or not text.strip():
        return False
    q = _normalize(text)
    return any(phrase in q for phrase in _CHALLENGE_PHRASES)


def speech_duration_s(gov: dict) -> float:
    started = gov.get("user_speech_started_at")
    if not isinstance(started, (int, float)) or started <= 0:
        return 0.0
    return max(0.0, time.monotonic() - started)


def mark_user_speech_start(gov: dict) -> None:
    if not gov.get("user_speech_started_at"):
        gov["user_speech_started_at"] = time.monotonic()


def clear_user_speech_start(gov: dict) -> None:
    gov["user_speech_started_at"] = 0.0


def should_allow_barge_in(
    gov: dict,
    *,
    transcript: str | None = None,
    dialect: str | None = None,
    client_rms: bool = False,
) -> bool:
    """Filter barge-in Papua: filler pendek ditolak; potong alami & penantang diterima."""
    from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

    if not is_papua_dialect(dialect):
        return True

    if client_rms:
        if gov.get("embedded_app"):
            last_fwd = gov.get("last_forward_at")
            if isinstance(last_fwd, (int, float)) and last_fwd > 0:
                hold = 13.0 if gov.get("embedded_app") else 3.0
                if time.monotonic() - last_fwd < hold:
                    return False
            if gov.get("floor") == "agent" or gov.get("model_generating"):
                return False
        return True

    text = (transcript or gov.get("partial_text") or gov.get("last_user_transcript") or "").strip()
    duration = speech_duration_s(gov)

    if text and is_filler_only(text):
        return False

    if text and is_challenge_interrupt(text):
        return True

    words = [w for w in re.split(r"[^\w']+", _normalize(text)) if w]
    if text and len(words) >= 3 and not is_filler_only(text):
        if duration >= 0.55 or len(words) >= 5:
            return True

    if duration >= MIN_CHALLENGE_DURATION_S and text and not is_filler_only(text):
        return is_challenge_interrupt(text)

    return False


def barge_ack_steer_text(dialect: str | None) -> str:
    """Deprecated — steer inject made Gemini say one filler then stay silent."""
    del dialect
    return ""
