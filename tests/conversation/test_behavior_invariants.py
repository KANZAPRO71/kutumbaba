"""Cross-stack invariants — A–D behavioral safety net."""

from __future__ import annotations

from pathlib import Path

import pytest

from persona_ai.behavior.engine import decide
from persona_ai.conversation.callback_gate import (
    evaluate_loop_callback,
    select_callback_candidate,
    surface_callback_if_allowed,
)
from persona_ai.conversation.mop_engine import (
    MopPhase,
    evaluate_mop_eligibility,
    get_mop_session,
    mop_frequency_for_mode,
    on_assistant_mop_complete,
    plan_mop_turn,
    reset_mop_sessions,
)
from persona_ai.core.types import BehaviorInput, Message, SpeakAction
from persona_ai.memory.open_loop_extract import OpenLoopCandidate
from persona_ai.memory.open_loop_engine import create_open_loop, reset_open_loop_store


def _inp(text: str, *, mode: str = "nongkrong") -> BehaviorInput:
    return BehaviorInput(
        message=Message.from_text("user", text),
        conversation_mode=mode,
    )


@pytest.fixture
def isolated_stores(tmp_path, monkeypatch):
    db = tmp_path / "inv.db"
    monkeypatch.setenv("PERSONA_MEMORY_DB", str(db))
    reset_open_loop_store()
    from persona_ai.conversation.callback_daily_store import reset_callback_daily_store

    reset_callback_daily_store()
    reset_mop_sessions()
    yield
    reset_open_loop_store()
    reset_callback_daily_store()
    reset_mop_sessions()


def test_callback_does_not_bypass_bdv_silence(isolated_stores):
    reset_open_loop_store()
    create_open_loop(
        OpenLoopCandidate(
            topic="motor",
            content="Ko pertimbangkan beli motor baru",
            time_hint=None,
            confidence=0.88,
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


def test_mop_does_not_bypass_bdv_defer(isolated_stores):
    reset_mop_sessions()
    inp = _inp("Weh lucu banget tadi di warung", mode="mop")
    bdv = decide(inp).model_copy(update={"speak": SpeakAction.DEFER, "engagement_level": 0.8})
    state = get_mop_session("inv1")
    elig = evaluate_mop_eligibility(
        inp=inp,
        bdv=bdv,
        experience_mode="mop",
        session=state,
    )
    assert elig.eligible is False
    assert elig.reason == "bdv_defer"

    plan, _ = plan_mop_turn(
        session_id="inv1",
        inp=inp,
        bdv=bdv,
        experience_mode="mop",
        user_turn_index=1,
    )
    assert plan.suppressed is True
    assert plan.suppress_reason == "bdv_defer"


def test_teman_jalan_callback_disabled(isolated_stores):
    reset_open_loop_store()
    loop = create_open_loop(
        OpenLoopCandidate(
            topic="jalan",
            content="Ko mau jalan ke pantai weekend ini",
            time_hint=None,
            confidence=0.9,
        )
    )
    decision = evaluate_loop_callback(
        loop,
        experience_mode="teman_jalan",
        user_text="Sa jalan pelan nih",
        session_user_turns=2,
        callbacks_surfaced_today=0,
    )
    assert decision.eligible is False
    assert decision.reason == "mode_disallows_callback"


def test_cerita_tong_mop_off_and_conservative_questions(isolated_stores):
    reset_mop_sessions()
    from persona_ai.conversation.experience_modes import get_experience_profile

    profile = get_experience_profile("cerita_tong")
    assert profile.behavior.question_budget <= 1
    assert mop_frequency_for_mode("cerita_tong") == "off"

    inp = _inp("Sa cerita panjang tentang kampung halaman dan keluarga", mode="cerita_tong")
    bdv = decide(inp)
    plan, _ = plan_mop_turn(
        session_id="ct1",
        inp=inp,
        bdv=bdv,
        experience_mode="cerita_tong",
        user_turn_index=1,
    )
    assert plan.suppressed is True
    assert plan.suppress_reason == "mode_mop_off"


def test_mop_punchline_reaction_is_metadata_only(isolated_stores):
    """Native reaction stays cue-only — no PCM mutation in mop_engine."""
    reset_mop_sessions()
    sid = "react1"
    state = get_mop_session(sid)
    state.phase = MopPhase.PUNCHLINE
    state.current_type = "observational"
    reaction = on_assistant_mop_complete(
        sid,
        "Nah itu dia punchline yang cukup panjang untuk trigger reaction cue ya.",
        experience_mode="mop",
    )
    assert reaction in {"laugh_short", "soft_laugh", "jedag"}
    src = Path(__file__).resolve().parents[2] / "src" / "persona_ai" / "conversation" / "mop_engine.py"
    text = src.read_text(encoding="utf-8")
    assert "asyncio" not in text
    assert "sleep(" not in text


def test_mop_engine_has_no_blocking_delay(isolated_stores):
    src = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "persona_ai"
        / "conversation"
        / "mop_engine.py"
    )
    body = src.read_text(encoding="utf-8")
    assert "asyncio" not in body
    assert "time.sleep" not in body
    assert "await " not in body
