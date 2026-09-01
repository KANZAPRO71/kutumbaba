"""Agent timezone — current local time and relative time reference handling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from persona_ai.core.types import PersonalityProfile
from persona_ai.personality.preset import read_preset_json

_WEEKDAYS_ID = (
    "Senin",
    "Selasa",
    "Rabu",
    "Kamis",
    "Jumat",
    "Sabtu",
    "Minggu",
)
_WEEKDAYS_EN = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_MONTHS_ID = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)
_MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_TZ_ALIASES: dict[str, str] = {
    "WIB": "Asia/Jakarta",
    "WITA": "Asia/Makassar",
    "WIT": "Asia/Jayapura",
    "JKT": "Asia/Jakarta",
}


def normalize_timezone(name: str | None) -> str | None:
    """Return a valid IANA timezone name, or None if unset/invalid."""
    if not name or not isinstance(name, str):
        return None
    cleaned = name.strip()
    if not cleaned:
        return None
    upper = cleaned.upper()
    if upper in _TZ_ALIASES:
        return _TZ_ALIASES[upper]
    try:
        ZoneInfo(cleaned)
    except ZoneInfoNotFoundError:
        return None
    return cleaned


def resolve_zone(name: str | None) -> ZoneInfo | None:
    normalized = normalize_timezone(name)
    if normalized is None:
        return None
    return ZoneInfo(normalized)


def _offset_label(now: datetime) -> str:
    offset = now.strftime("%z")
    if not offset:
        return "local time"
    return f"UTC{offset[:3]}:{offset[3:]}"


def _local_labels(language: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if language == "id":
        return _WEEKDAYS_ID, _MONTHS_ID
    return _WEEKDAYS_EN, _MONTHS_EN


@dataclass(frozen=True)
class TimeAwarenessConfig:
    """Retell-style Current Time Awareness — agent IANA timezone."""

    timezone: str | None = None

    def __post_init__(self) -> None:
        normalized = normalize_timezone(self.timezone)
        object.__setattr__(self, "timezone", normalized)

    @property
    def is_set(self) -> bool:
        return self.timezone is not None

    def now(self) -> datetime | None:
        zone = resolve_zone(self.timezone)
        if zone is None:
            return None
        return datetime.now(zone)

    def current_datetime_line(self, *, language: str = "id") -> str:
        """Single-line clock fact for system prompts."""
        now = self.now()
        if now is None:
            if language == "id":
                return (
                    "Current Time Awareness: timezone agent belum diset. "
                    "Jangan asumsikan tanggal/jam lokal user. Jika user tanya waktu "
                    "atau jadwal, tanyakan timezone mereka atau katakan kamu belum punya "
                    "waktu lokal mereka."
                )
            return (
                "Current Time Awareness: no agent timezone set. "
                "Do not assume the user's local date or time. If they ask about time "
                "or scheduling, ask their timezone or say you don't have their local time."
            )
        weekdays, months = _local_labels(language)
        weekday = weekdays[now.weekday()]
        month = months[now.month - 1]
        offset = _offset_label(now)
        tz_name = self.timezone or offset
        if language == "id":
            return (
                f"Current Time Awareness: timezone agent {tz_name} ({offset}). "
                f"Waktu lokal sekarang: {weekday}, {now.day} {month} {now.year}, "
                f"{now:%H:%M}. Jawab pertanyaan waktu memakai jam ini."
            )
        return (
            f"Current Time Awareness: agent timezone {tz_name} ({offset}). "
            f"Local time now: {weekday}, {month} {now.day}, {now.year}, "
            f"{now:%H:%M}. Answer time questions using this clock."
        )

    def time_answer(self, *, language: str = "id") -> str:
        """Direct spoken answer for 'what time is it?' shortcuts."""
        now = self.now()
        if now is None:
            if language == "id":
                return (
                    "Timezone agent belum diset, jadi aku belum bisa kasih jam lokal pasti. "
                    "Kamu di timezone apa?"
                )
            return (
                "No agent timezone is set, so I can't give a precise local time yet. "
                "What timezone are you in?"
            )
        weekdays, months = _local_labels(language)
        weekday = weekdays[now.weekday()]
        month = months[now.month - 1]
        offset = _offset_label(now)
        if language == "id":
            return (
                f"Sekarang pukul {now:%H:%M} ({offset}), {weekday}, "
                f"{now.day} {month} {now.year}."
            )
        return (
            f"It's {now:%H:%M} ({offset}), {weekday}, {month} {now.day}, {now.year}."
        )

    def interpretation_lines(self, *, language: str = "id") -> list[str]:
        """How to read relative time references against the agent clock."""
        if not self.is_set:
            return []
        if language == "id":
            return [
                "Interpretasi waktu relatif (timezone agent): "
                "'hari ini', 'besok', 'lusa', 'minggu depan', '2 jam lagi', "
                "'pagi/sore/malam', dan jam kerja — pakai waktu lokal agent di atas. "
                "Untuk jadwal, konfirmasi tanggal dan jam secara eksplisit.",
            ]
        return [
            "Relative time interpretation (agent timezone): "
            "'today', 'tomorrow', 'in 2 hours', business hours, and scheduling windows — "
            "use the agent local time above. For appointments, confirm date and time explicitly.",
        ]

    def prompt_lines(self, *, language: str = "id") -> list[str]:
        lines = [self.current_datetime_line(language=language)]
        lines.extend(self.interpretation_lines(language=language))
        return lines

    def to_client_dict(self) -> dict[str, str | None]:
        return {"timezone": self.timezone}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimeAwarenessConfig:
        tz = data.get("timezone")
        return cls(timezone=str(tz).strip() if tz else None)

    @classmethod
    def from_profile(cls, profile: PersonalityProfile) -> TimeAwarenessConfig:
        preset_id = profile.preset_id or "default_companion"
        try:
            raw = read_preset_json(preset_id)
        except (FileNotFoundError, OSError):
            return cls()
        block = raw.get("time_awareness")
        if isinstance(block, dict):
            return cls.from_dict(block)
        return cls()
