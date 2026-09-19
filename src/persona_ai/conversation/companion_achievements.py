"""Local-only milestone badges derived from companion stats — no cloud."""

from __future__ import annotations

from dataclasses import dataclass

from persona_ai.conversation.companion_stats import CompanionStats


@dataclass(frozen=True)
class CompanionAchievement:
    id: str
    title: str
    emoji: str
    description: str


_CATALOG: tuple[CompanionAchievement, ...] = (
    CompanionAchievement(
        id="first_hello",
        title="Perkenalan",
        emoji="👋",
        description="Selesaiin panggilan pertama bareng Papua AI.",
    ),
    CompanionAchievement(
        id="streak_3",
        title="Tongkrong 3 hari",
        emoji="🔥",
        description="Ngobrol 3 hari berturut-turut.",
    ),
    CompanionAchievement(
        id="streak_7",
        title="Satu minggu teman",
        emoji="⭐",
        description="Streak 7 hari — konsisten banget.",
    ),
    CompanionAchievement(
        id="ten_sessions",
        title="Langganan tong",
        emoji="🗣️",
        description="Total 10 sesi ngobrol.",
    ),
    CompanionAchievement(
        id="hour_together",
        title="Satu jam bareng",
        emoji="⏱️",
        description="Kumpul ~60 menit total (semua panggilan).",
    ),
)


def _unlocked(achievement_id: str, stats: CompanionStats) -> bool:
    minutes = stats.total_duration_ms // 60_000
    if achievement_id == "first_hello":
        return stats.total_sessions >= 1
    if achievement_id == "streak_3":
        return stats.streak_days >= 3
    if achievement_id == "streak_7":
        return stats.streak_days >= 7
    if achievement_id == "ten_sessions":
        return stats.total_sessions >= 10
    if achievement_id == "hour_together":
        return minutes >= 60
    return False


def achievements_for_client(stats: CompanionStats) -> list[dict[str, str | bool]]:
    rows: list[dict[str, str | bool]] = []
    for item in _CATALOG:
        rows.append(
            {
                "id": item.id,
                "title": item.title,
                "emoji": item.emoji,
                "description": item.description,
                "unlocked": _unlocked(item.id, stats),
            }
        )
    return rows
