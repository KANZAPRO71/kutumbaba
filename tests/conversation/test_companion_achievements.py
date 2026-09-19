"""Companion achievement badges — derived from local stats only."""

from __future__ import annotations

from persona_ai.conversation.companion_achievements import achievements_for_client
from persona_ai.conversation.companion_stats import CompanionStats


def test_fresh_user_all_locked():
    rows = achievements_for_client(CompanionStats())
    assert len(rows) == 5
    assert all(not row["unlocked"] for row in rows)


def test_first_session_unlocks_hello():
    stats = CompanionStats(total_sessions=1, total_duration_ms=30_000)
    rows = {r["id"]: r for r in achievements_for_client(stats)}
    assert rows["first_hello"]["unlocked"] is True
    assert rows["streak_3"]["unlocked"] is False


def test_streak_and_hour_milestones():
    stats = CompanionStats(
        streak_days=7,
        total_sessions=12,
        total_duration_ms=61 * 60_000,
    )
    rows = {r["id"]: r for r in achievements_for_client(stats)}
    assert rows["streak_3"]["unlocked"] is True
    assert rows["streak_7"]["unlocked"] is True
    assert rows["ten_sessions"]["unlocked"] is True
    assert rows["hour_together"]["unlocked"] is True
