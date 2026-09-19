"""Soft daily check-in — companion presence, not notification spam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from persona_ai.conversation.companion_stats import load_companion_stats
from persona_ai.conversation.daily import DayPart, day_part_from_hour
from persona_ai.conversation.proactive_followup import (
    latest_pending_open_loop,
    live_hint_from_open_loop,
    message_from_open_loop,
)
from persona_ai.core.types import PersonalityProfile
from persona_ai.web.time_awareness import TimeAwarenessConfig


@dataclass(frozen=True)
class DailyCheckIn:
    show: bool
    day_part: str
    message: str
    live_hint: str
    talked_today: bool
    follow_up_kind: str = "generic"
    open_loop_id: str | None = None


def _messages(day_part: DayPart, *, language: str) -> tuple[str, str]:
    """Banner message + optional live tone hint."""
    if language == "id":
        by_part = {
            DayPart.MORNING: (
                "Pagi deng ko? Kalau mau cerita sebentar, tekan Ngobrol.",
                "Pagi — sapa ringan, jangan paksa rencana.",
            ),
            DayPart.AFTERNOON: (
                "Siang ini gimana? Sa di sini kalau ko mau ngobrol bentar.",
                "Siang — check-in singkat kalau ko buka obrolan.",
            ),
            DayPart.EVENING: (
                "Sore sudah — mau curhat atau ngobrol santai sebentar?",
                "Sore — lebih rileks, ikuti ko.",
            ),
            DayPart.NIGHT: (
                "Malam ini masih bangun? Cerita sebentar juga oke.",
                "Malam — lembut dan pendek kecuali ko minta lanjut.",
            ),
        }
    else:
        by_part = {
            DayPart.MORNING: ("Good morning — tap Call if you want a quick chat.", "Morning — light greeting only."),
            DayPart.AFTERNOON: ("How's your day? I'm here if you want to talk.", "Afternoon — soft check-in."),
            DayPart.EVENING: ("Evening — want a short hangout call?", "Evening — relaxed tone."),
            DayPart.NIGHT: ("Still up? A short voice chat is fine.", "Night — gentle and brief."),
        }
    return by_part.get(day_part, by_part[DayPart.AFTERNOON])


def evaluate_daily_checkin(profile: PersonalityProfile) -> DailyCheckIn:
    stats = load_companion_stats()
    today = date.today().isoformat()
    talked_today = stats.last_talk_date == today

    time_cfg = TimeAwarenessConfig.from_profile(profile)
    now = time_cfg.now()
    if now is None:
        return DailyCheckIn(
            show=False,
            day_part="unknown",
            message="",
            live_hint="",
            talked_today=talked_today,
        )

    part = day_part_from_hour(now.hour)
    lang = profile.default_language or "id"
    message, live_hint = _messages(part, language=lang)
    follow_up_kind = "generic"
    open_loop_id: str | None = None

    loop = latest_pending_open_loop()
    if loop is not None:
        follow_up_kind = "open_loop_pending"
        open_loop_id = loop.id
        live_hint = live_hint_from_open_loop(loop, language=lang)

    show = not talked_today
    return DailyCheckIn(
        show=show,
        day_part=part.value,
        message=message,
        live_hint=live_hint,
        talked_today=talked_today,
        follow_up_kind=follow_up_kind,
        open_loop_id=open_loop_id,
    )
