"""Observe turn lifecycle for Experience Mode telemetry — does not control transport."""

from __future__ import annotations

import re
import time
from typing import Any

from persona_ai.conversation.experience_modes import normalize_experience_mode
from persona_ai.conversation.experience_telemetry import log_session_summary, log_turn_metric
from persona_ai.runtime import PersonaRuntime

_QUESTION_RE = re.compile(r"\?")


def _empty_session_stats() -> dict[str, Any]:
    return {
        "experience_mode": "",
        "user_talk_duration_ms": 0,
        "assistant_talk_duration_ms": 0,
        "listening_ratio": 0.0,
        "user_turns": 0,
        "assistant_turns": 0,
        "question_count": 0,
        "ack_only_count": 0,
        "defer_count": 0,
        "silence_count": 0,
        "interruption_count": 0,
        "turns": [],
    }


def init_experience_stats(gov: dict, *, conversation_mode: str | None) -> None:
    stats = _empty_session_stats()
    stats["experience_mode"] = normalize_experience_mode(conversation_mode)
    gov["experience_session_stats"] = stats


def note_user_turn_final(gov: dict, *, now: float | None = None) -> None:
    """Call when user ASR finalizes — duration from activity window."""
    clock = now if now is not None else time.monotonic()
    gov["last_user_final_at"] = clock
    started = gov.get("activity_started_at")
    if isinstance(started, (int, float)) and clock >= started:
        gov["last_user_talk_ms"] = int(max(0.0, (clock - started) * 1000))
    else:
        gov["last_user_talk_ms"] = 0


def note_governance_bdv(gov: dict, bdv: str | None) -> None:
    if bdv:
        gov["last_experience_bdv"] = str(bdv).strip().upper()


def note_interruption(gov: dict) -> None:
    stats = gov.get("experience_session_stats")
    if isinstance(stats, dict):
        stats["interruption_count"] = int(stats.get("interruption_count") or 0) + 1


def _estimate_speech_ms(text: str) -> int:
    words = len((text or "").split())
    if words <= 0:
        return 0
    return max(350, int(words * 320))


def _resolve_bdv(
    gov: dict,
    *,
    runtime: PersonaRuntime | None,
    session_id: str,
    user_text: str,
) -> str:
    cached = gov.get("last_experience_bdv")
    if isinstance(cached, str) and cached.strip():
        return cached.strip().upper()
    if not runtime or not user_text.strip():
        return "UNKNOWN"
    try:
        # Ephemeral snapshot only — commit_state=False; no session/arc persistence.
        output = runtime.process_turn(
            session_id,
            user_text.strip(),
            persist=False,
            channel="voice",
            generate_text=False,
            conversation_mode=gov.get("conversation_mode"),
        )
        if output.bdv:
            return output.bdv.speak.value
    except Exception:
        pass
    return "UNKNOWN"


def record_experience_turn(
    gov: dict,
    *,
    runtime: PersonaRuntime | None,
    session_id: str,
    assistant_text: str | None,
) -> None:
    """Call once per completed assistant turn (turn boundary observer)."""
    stats = gov.get("experience_session_stats")
    if not isinstance(stats, dict):
        return

    mode = normalize_experience_mode(gov.get("conversation_mode"))
    stats["experience_mode"] = mode

    user_text = (gov.get("last_governed_transcript") or gov.get("last_user_transcript") or "").strip()
    user_ms = int(gov.get("last_user_talk_ms") or 0)
    if user_ms <= 0 and user_text:
        user_ms = _estimate_speech_ms(user_text)

    assistant_clean = (assistant_text or "").strip()
    assistant_ms = _estimate_speech_ms(assistant_clean) if assistant_clean else 0

    bdv = _resolve_bdv(gov, runtime=runtime, session_id=session_id, user_text=user_text)
    question_count = len(_QUESTION_RE.findall(assistant_clean))
    silence = bdv in {"SILENCE", "DEFER"} and not assistant_clean

    turn_payload = {
        "session_id": session_id,
        "experience_mode": mode,
        "user_talk_duration_ms": user_ms,
        "assistant_duration_ms": assistant_ms,
        "bdv": bdv,
        "question_count": question_count,
        "silence": silence,
        "interruption": False,
    }
    log_turn_metric(turn_payload)

    stats["user_turns"] = int(stats.get("user_turns") or 0) + (1 if user_text else 0)
    stats["assistant_turns"] = int(stats.get("assistant_turns") or 0) + (1 if assistant_clean else 0)
    stats["user_talk_duration_ms"] = int(stats.get("user_talk_duration_ms") or 0) + user_ms
    stats["assistant_talk_duration_ms"] = int(stats.get("assistant_talk_duration_ms") or 0) + assistant_ms
    stats["question_count"] = int(stats.get("question_count") or 0) + question_count
    if bdv == "ACK_ONLY":
        stats["ack_only_count"] = int(stats.get("ack_only_count") or 0) + 1
    elif bdv == "DEFER":
        stats["defer_count"] = int(stats.get("defer_count") or 0) + 1
    elif bdv == "SILENCE":
        stats["silence_count"] = int(stats.get("silence_count") or 0) + 1

    turns = stats.get("turns")
    if not isinstance(turns, list):
        turns = []
    turns.append(turn_payload)
    stats["turns"] = turns[-40:]

    total = stats["user_talk_duration_ms"] + stats["assistant_talk_duration_ms"]
    stats["listening_ratio"] = (
        round(stats["user_talk_duration_ms"] / total, 4) if total > 0 else 0.0
    )

    gov["last_experience_bdv"] = None
    gov["last_user_talk_ms"] = 0


def log_session_behavior_summary(gov: dict, *, session_id: str) -> None:
    """Observer-only — flush session rollup for behavior eval distributions."""
    stats = gov.get("experience_session_stats")
    if not isinstance(stats, dict) or not session_id:
        return
    mode = normalize_experience_mode(gov.get("conversation_mode"))
    user_ms = int(stats.get("user_talk_duration_ms") or 0)
    asst_ms = int(stats.get("assistant_talk_duration_ms") or 0)
    total = user_ms + asst_ms
    turns = int(stats.get("user_turns") or 0) or int(stats.get("assistant_turns") or 0)
    listening_ratio = float(stats.get("listening_ratio") or 0.0)
    if total > 0 and listening_ratio <= 0:
        listening_ratio = round(user_ms / total, 4)
    counts = gov.get("behavior_session_counts")
    mop_selected = 0
    callback_surfaced = 0
    if isinstance(counts, dict):
        mop_selected = int(counts.get("mop_selected") or 0)
        callback_surfaced = int(counts.get("callback_surfaced") or 0)
    config_revision = None
    try:
        from persona_ai.conversation.behavior_config_revision import current_revision

        config_revision = current_revision()
    except Exception:
        pass
    log_session_summary(
        {
            "session_id": session_id,
            "experience_mode": mode,
            "config_revision": config_revision,
            "turns": turns,
            "user_talk_ms": user_ms,
            "assistant_talk_ms": asst_ms,
            "listening_ratio": listening_ratio,
            "listening_percent": int(round(listening_ratio * 100)) if total > 0 else 0,
            "avg_assistant_s": round(asst_ms / max(1, turns) / 1000.0, 1),
            "questions": int(stats.get("question_count") or 0),
            "mop_selected_turns": mop_selected,
            "mop_percent": int(round(100.0 * mop_selected / turns)) if turns else 0,
            "callback_surfaced": callback_surfaced,
            "interruptions": int(stats.get("interruption_count") or 0),
        }
    )


def note_behavior_session_mop(gov: dict) -> None:
    counts = gov.setdefault("behavior_session_counts", {})
    if isinstance(counts, dict):
        counts["mop_selected"] = int(counts.get("mop_selected") or 0) + 1


def note_behavior_session_callback(gov: dict) -> None:
    counts = gov.setdefault("behavior_session_counts", {})
    if isinstance(counts, dict):
        counts["callback_surfaced"] = int(counts.get("callback_surfaced") or 0) + 1


def merge_stats_into_post_call(post_call: dict[str, Any] | None, gov: dict) -> dict[str, Any] | None:
    stats = gov.get("experience_session_stats")
    if not isinstance(post_call, dict) or not isinstance(stats, dict):
        return post_call
    merged = dict(post_call)
    merged["experience_telemetry"] = dict(stats)
    return merged
