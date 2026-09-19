"""Daily check-in evaluation."""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from persona_ai.conversation.companion_stats import (
    CompanionStats,
    get_companion_stats_store,
    reset_companion_stats_store,
)
from persona_ai.conversation.daily_checkin import evaluate_daily_checkin
from persona_ai.memory.open_loop_engine import create_open_loop, reset_open_loop_store
from persona_ai.memory.open_loop_extract import OpenLoopCandidate
from persona_ai.memory.engine import reset_memory_store
from persona_ai.personality.preset import load_default_preset


@pytest.fixture
def memory_db(monkeypatch):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "user_memory.db"
        monkeypatch.setenv("PERSONA_MEMORY_DB", str(db_path))
        reset_companion_stats_store()
        reset_memory_store()
        reset_open_loop_store()
        yield
        reset_companion_stats_store()
        reset_memory_store()
        reset_open_loop_store()


def test_checkin_hidden_after_talk_today(memory_db):
    store = get_companion_stats_store()
    store.save(
        CompanionStats(
            streak_days=2,
            last_talk_date=date.today().isoformat(),
            total_sessions=3,
        )
    )
    profile = load_default_preset()
    with patch("persona_ai.conversation.daily_checkin.TimeAwarenessConfig") as mock_cfg:
        inst = mock_cfg.from_profile.return_value
        from datetime import datetime, timezone

        inst.now.return_value = datetime(2026, 9, 19, 8, 30, tzinfo=timezone.utc)
        result = evaluate_daily_checkin(profile)
    assert result.talked_today is True
    assert result.show is False


def test_checkin_shows_when_not_talked(memory_db):
    profile = load_default_preset()
    with patch("persona_ai.conversation.daily_checkin.TimeAwarenessConfig") as mock_cfg:
        inst = mock_cfg.from_profile.return_value
        from datetime import datetime, timezone

        inst.now.return_value = datetime(2026, 9, 19, 8, 30, tzinfo=timezone.utc)
        result = evaluate_daily_checkin(profile)
    assert result.show is True
    assert result.message
    assert result.day_part == "morning"


def test_checkin_uses_open_loop_content(memory_db):
    create_open_loop(
        OpenLoopCandidate(
            topic="rapat",
            content="Besok sa ada rapat dengan tim desain",
            time_hint="besok",
            confidence=0.9,
        ),
    )
    profile = load_default_preset()
    with patch("persona_ai.conversation.daily_checkin.TimeAwarenessConfig") as mock_cfg:
        inst = mock_cfg.from_profile.return_value
        from datetime import datetime, timezone

        inst.now.return_value = datetime(2026, 9, 19, 8, 30, tzinfo=timezone.utc)
        result = evaluate_daily_checkin(profile)
    assert result.show is True
    assert result.follow_up_kind == "open_loop"
    assert "rapat dengan tim desain" in result.message
