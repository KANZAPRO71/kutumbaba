"""Human-readable Session Memory Card — product layer over post_call + session."""

from __future__ import annotations

from typing import Any

from persona_ai.core.types import Message
from persona_ai.web.session_memory import collapse_history, post_call_summary


def _trim(text: str, limit: int = 140) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _sentiment_label(raw: str | None, *, language: str = "id") -> str:
    key = (raw or "").strip().lower()
    if language == "id":
        mapping = {
            "positive": "Ceria / hangat",
            "neutral": "Santai",
            "negative": "Agak berat",
        }
        return mapping.get(key, "Santai")
    mapping = {"positive": "Warm", "neutral": "Calm", "negative": "Heavy"}
    return mapping.get(key, "Calm")


def _first_user_story(messages: list[Message]) -> str | None:
    collapsed = collapse_history(list(messages or []))
    for msg in collapsed:
        if msg.role != "user":
            continue
        text = _trim(msg.text or "", 160)
        if len(text) >= 12:
            return text
    return None


def _memory_lines(post_call: dict | None, *, limit: int = 2) -> list[str]:
    if not isinstance(post_call, dict):
        return []
    data = post_call.get("data")
    if not isinstance(data, dict):
        return []
    raw = data.get("user_memories")
    if not isinstance(raw, list):
        return []
    lines: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            lines.append(_trim(item.strip(), 120))
        elif isinstance(item, dict):
            content = item.get("content") or item.get("text") or ""
            if isinstance(content, str) and content.strip():
                lines.append(_trim(content.strip(), 120))
        if len(lines) >= limit:
            break
    return lines


def _open_loop_lines(post_call: dict | None, *, limit: int = 2) -> list[str]:
    if not isinstance(post_call, dict):
        return []
    data = post_call.get("data")
    if not isinstance(data, dict):
        return []
    raw = data.get("open_loops")
    if not isinstance(raw, list):
        return []
    lines: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        content = (item.get("content") or "").strip()
        if content:
            lines.append(_trim(content, 120))
        if len(lines) >= limit:
            break
    return lines


def _follow_up_line(open_loops: list[str], *, language: str = "id") -> str | None:
    if not open_loops:
        return None
    snippet = open_loops[0]
    if language == "id":
        return f"Besok Tra bisa tanya: «{_trim(snippet, 80)} — jadi gimana?»"
    return f"Next time: «{_trim(snippet, 80)} — how did it go?»"


def build_session_memory_card(
    *,
    session_id: str,
    messages: list[Message] | None,
    post_call: dict[str, Any] | None,
    experience_mode: str | None = None,
    language: str = "id",
) -> dict[str, Any]:
    """Structured card for UI — not a raw DB dump."""
    summary = post_call_summary(post_call)
    story = summary or _first_user_story(list(messages or []))
    remember = _memory_lines(post_call)
    unfinished = _open_loop_lines(post_call)
    telemetry = {}
    if isinstance(post_call, dict):
        telemetry = post_call.get("experience_telemetry") or {}

    sentiment = None
    if isinstance(post_call, dict):
        data = post_call.get("data")
        if isinstance(data, dict):
            sentiment = data.get("user_sentiment")

    listening_ratio = float(telemetry.get("listening_ratio") or 0.0)
    listening_pct = int(round(listening_ratio * 100)) if listening_ratio > 0 else None

    card = {
        "session_id": session_id,
        "title": "Tadi Tong Bicara" if language == "id" else "You spoke today",
        "experience_mode": experience_mode or telemetry.get("experience_mode") or "",
        "sections": {
            "story": story,
            "remember": remember,
            "unfinished": unfinished,
            "mood": _sentiment_label(str(sentiment) if sentiment else None, language=language),
            "follow_up": _follow_up_line(unfinished, language=language),
        },
        "listening_balance": {
            "ratio": listening_ratio,
            "percent": listening_pct,
            "label": "Listening Balance" if language != "id" else "Listening Balance",
            "caption": (
                "Papua AI lebih banyak mendengar daripada bicara."
                if language == "id" and listening_pct and listening_pct >= 50
                else (
                    "Papua AI dan ko seimbang ngobrolnya."
                    if language == "id"
                    else "Balanced conversation."
                )
            ),
        },
        "telemetry_summary": {
            "user_talk_duration_ms": int(telemetry.get("user_talk_duration_ms") or 0),
            "assistant_talk_duration_ms": int(telemetry.get("assistant_talk_duration_ms") or 0),
            "question_count": int(telemetry.get("question_count") or 0),
            "ack_only_count": int(telemetry.get("ack_only_count") or 0),
            "defer_count": int(telemetry.get("defer_count") or 0),
            "silence_count": int(telemetry.get("silence_count") or 0),
            "interruption_count": int(telemetry.get("interruption_count") or 0),
        },
    }
    return card
