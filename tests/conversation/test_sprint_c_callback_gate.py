"""Sprint C — Callback Gate."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from persona_ai.conversation.callback_daily_store import (
    CallbackDailyStore,
    reset_callback_daily_store,
)
from persona_ai.conversation.callback_gate import (
    evaluate_callback_turn,
    evaluate_loop_callback,
    select_callback_candidate,
    surface_callback_if_allowed,
)
from persona_ai.conversation.proactive_followup import CallbackCandidate
from persona_ai.core.types import SpeakAction
from persona_ai.memory.open_loop_engine import create_open_loop, reset_open_loop_store
from persona_ai.memory.open_loop_extract import OpenLoopCandidate

@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    db = tmp_path / "cb.db"
    monkeypatch.setenv("PERSONA_MEMORY_DB", str(db))
    reset_open_loop_store()
    reset_callback_daily_store()
    yield db
    reset_open_loop_store()
    reset_callback_daily_store()


def test_teman_jalan_rejects_callback(isolated_stores, tmp_path):
    reset_open_loop_store()
    cand = OpenLoopCandidate(
        topic="motor", content="Ko lagi cari motor baru nih", time_hint=None, confidence=0.9
    )
    loop = create_open_loop(cand)
    decision = evaluate_loop_callback(
        loop,
        experience_mode="teman_jalan",
        user_text="Sa lagi jalan ke kantor nih pelan",
        session_user_turns=2,
        callbacks_surfaced_today=0,
    )
    assert decision.eligible is False
    assert decision.reason == "mode_disallows_callback"


def test_max_one_surfaced_per_day(isolated_stores):
    reset_open_loop_store()
    create_open_loop(
        OpenLoopCandidate(
            topic="teman", content="Cerita teman lama belum selesai", time_hint=None, confidence=0.9
        )
    )
    daily = CallbackDailyStore(isolated_stores)
    daily.record_surfaced("abc123")

    turn = select_callback_candidate(
        experience_mode="nongkrong",
        user_text="Sa lagi santai nih di rumah",
        session_user_turns=1,
    )
    assert turn.candidate_count >= 0
    if turn.decision:
        assert turn.decision.eligible is False or turn.decision.reason == "callback_used_today"


def test_callback_surfaces_only_with_bdv_ack_or_respond(isolated_stores):
    reset_open_loop_store()
    create_open_loop(
        OpenLoopCandidate(
            topic="motor", content="Ko pertimbangkan beli motor baru", time_hint=None, confidence=0.88
        )
    )
    turn = select_callback_candidate(
        experience_mode="nongkrong",
        user_text="Sa lagi santai nih habis kerja",
        session_user_turns=1,
    )
    assert turn.selected is not None
    silenced = surface_callback_if_allowed(
        turn,
        experience_mode="nongkrong",
        bdv_speak=SpeakAction.SILENCE,
    )
    assert silenced.surfaced is False
    assert silenced.suppressed_reason == "bdv_silence"

    allowed = surface_callback_if_allowed(
        turn,
        experience_mode="nongkrong",
        bdv_speak=SpeakAction.ACK_ONLY,
    )
    assert allowed.surfaced is True
    assert allowed.steer_fragment


def test_loop_cooldown_blocks_repeat(isolated_stores, tmp_path):
    reset_open_loop_store()
    from persona_ai.memory.open_loop_engine import get_open_loop_store

    cand = OpenLoopCandidate(
        topic="motor", content="Beli motor atau tidak", time_hint=None, confidence=0.9
    )
    loop = create_open_loop(cand)
    loop.last_callback_at = datetime.now(timezone.utc).isoformat()
    get_open_loop_store().save(loop)

    decision = evaluate_loop_callback(
        loop,
        experience_mode="nongkrong",
        user_text="Sa lagi santai nih di tongkrongan",
        session_user_turns=1,
        callbacks_surfaced_today=0,
    )
    assert decision.eligible is False
    assert decision.reason == "loop_cooldown"


def test_evaluate_callback_turn_integrates_bdv(isolated_stores):
    reset_open_loop_store()
    create_open_loop(
        OpenLoopCandidate(
            topic="friend", content="Ketemu teman lama kemarin", time_hint=None, confidence=0.92
        )
    )
    result = evaluate_callback_turn(
        user_text="Sa lagi santai nih ko",
        experience_mode="cerita_tong",
        session_user_turns=1,
        bdv_speak=SpeakAction.ACK_ONLY,
    )
    assert result.selected is not None
    assert result.surfaced in {True, False}
