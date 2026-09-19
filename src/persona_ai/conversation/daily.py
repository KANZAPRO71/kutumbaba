"""Daily conversation rhythm — time-of-day companion tone (prompt-only)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum


class DayPart(str, Enum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


def day_part_from_hour(hour: int) -> DayPart:
    if 5 <= hour < 11:
        return DayPart.MORNING
    if 11 <= hour < 17:
        return DayPart.AFTERNOON
    if 17 <= hour < 22:
        return DayPart.EVENING
    return DayPart.NIGHT


def daily_companion_lines(
    day_part: DayPart,
    *,
    language: str = "id",
    dialect: str | None = None,
) -> list[str]:
    papua = dialect and dialect.strip().lower() in {"papua", "papuan", "logat_papua", "papua_id"}
    use_id = language == "id" and papua

    if use_id:
        header = "Konteks hari (internal — jangan bacakan seperti alarm):"
        by_part = {
            DayPart.MORNING: [
                "Pagi: bisa sapa ringan kalau ko baru mulai (bangun? kopi?) — satu kalimat, tra panjang.",
                "Jangan paksa rencana harian kecuali ko bahas sendiri.",
            ],
            DayPart.AFTERNOON: [
                "Siang: check-in santai boleh ('hari ko gimana?') — singkat, bukan survey.",
            ],
            DayPart.EVENING: [
                "Sore/malem awal: teman tongkrongan — lebih rileks, bisa cerita ringan.",
            ],
            DayPart.NIGHT: [
                "Malam: suara & tempo lebih lembut; jangan panjang-panjang kecuali ko minta.",
                "Kalau ko sounds sleepy, wrap singkat — 'oke, istirahat dulu'.",
            ],
        }
    else:
        header = "Daily rhythm (internal — do not read like an alarm):"
        by_part = {
            DayPart.MORNING: ["Morning: light greeting ok — one short line, no agenda."],
            DayPart.AFTERNOON: ["Afternoon: soft check-in ok — one short line."],
            DayPart.EVENING: ["Evening: relaxed hangout energy."],
            DayPart.NIGHT: ["Night: gentler, shorter turns unless they ask for more."],
        }

    lines = [header, *by_part.get(day_part, [])]
    return lines


def daily_lines_for_datetime(
    now: datetime,
    *,
    language: str = "id",
    dialect: str | None = None,
) -> list[str]:
    return daily_companion_lines(
        day_part_from_hour(now.hour),
        language=language,
        dialect=dialect,
    )
