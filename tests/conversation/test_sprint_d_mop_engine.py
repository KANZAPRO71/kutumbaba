"""Sprint D — MOP Engine state, suppression, cooldown, reaction cues."""

from __future__ import annotations

from persona_ai.behavior.engine import decide
from persona_ai.conversation.mop_engine import (
    MopPhase,
    evaluate_mop_eligibility,
    get_mop_session,
    on_assistant_mop_complete,
    plan_mop_turn,
    reset_mop_sessions,
    MAX_MOPS_PER_SESSION,
    MIN_TURNS_BETWEEN_MOPS,
)
from persona_ai.core.types import BehaviorInput, Message, SpeakAction


def _inp(text: str, *, mode: str = "mop") -> BehaviorInput:
    return BehaviorInput(
        message=Message.from_text("user", text),
        conversation_mode=mode,
    )


def test_serious_user_suppresses_mop():
    reset_mop_sessions()
    inp = _inp("Ah capek banget hari ini berat sekali ya ampun")
    bdv = decide(inp)
    state = get_mop_session("s1")
    elig = evaluate_mop_eligibility(
        inp=inp,
        bdv=bdv,
        experience_mode="mop",
        session=state,
    )
    assert elig.eligible is False
    assert elig.reason == "user_serious"


def test_cerita_tong_mode_off():
    reset_mop_sessions()
    inp = _inp("Tadi sa ketemu teman lama di pasar Jayapura", mode="cerita_tong")
    bdv = decide(inp)
    state = get_mop_session("s2")
    elig = evaluate_mop_eligibility(
        inp=inp,
        bdv=bdv,
        experience_mode="cerita_tong",
        session=state,
    )
    assert elig.eligible is False
    assert elig.reason == "mode_mop_off"


def test_state_transition_setup_to_hold_to_punchline():
    reset_mop_sessions()
    sid = "s3"
    inp = _inp("Weh tadi kejadian lucu banget di warung")
    bdv = decide(inp)
    bdv = bdv.model_copy(update={"engagement_level": 0.75, "speak": SpeakAction.RESPOND})

    plan1, st1 = plan_mop_turn(
        session_id=sid,
        inp=inp,
        bdv=bdv,
        experience_mode="mop",
        user_turn_index=1,
    )
    assert plan1.phase == MopPhase.SETUP
    assert plan1.steer_fragment and "SETUP" in plan1.steer_fragment

    plan2, st2 = plan_mop_turn(
        session_id=sid,
        inp=inp,
        bdv=bdv,
        experience_mode="mop",
        user_turn_index=2,
    )
    assert plan2.phase == MopPhase.HOLD
    assert plan2.timing_delay_ms >= 300

    plan3, _ = plan_mop_turn(
        session_id=sid,
        inp=inp,
        bdv=bdv,
        experience_mode="mop",
        user_turn_index=3,
    )
    assert plan3.phase == MopPhase.PUNCHLINE
    assert plan3.reaction_after_turn is True


def test_cooldown_suppresses_back_to_back():
    reset_mop_sessions()
    sid = "s4"
    state = get_mop_session(sid)
    state.phase = MopPhase.COOLDOWN
    state.turns_since_last_mop = 0
    inp = _inp("Lagi bercanda nih ko")
    bdv = decide(inp)
    bdv = bdv.model_copy(update={"engagement_level": 0.8, "speak": SpeakAction.RESPOND})
    plan, _ = plan_mop_turn(
        session_id=sid,
        inp=inp,
        bdv=bdv,
        experience_mode="mop",
        user_turn_index=5,
    )
    assert plan.suppressed is True
    assert plan.suppress_reason == "cooldown_active"

    state.turns_since_last_mop = MIN_TURNS_BETWEEN_MOPS
    plan2, _ = plan_mop_turn(
        session_id=sid,
        inp=inp,
        bdv=bdv,
        experience_mode="mop",
        user_turn_index=6,
    )
    assert plan2.suppressed is False


def test_punchline_emits_reaction_metadata_not_pcm():
    reset_mop_sessions()
    sid = "s5"
    state = get_mop_session(sid)
    state.phase = MopPhase.PUNCHLINE
    reaction = on_assistant_mop_complete(
        sid,
        "…ternyata yang dia cari bukan dompet tapi alasan pulang cepat 😂",
        experience_mode="mop",
    )
    assert reaction in {"laugh_short", "soft_laugh", "none"}
    assert state.phase in {MopPhase.COOLDOWN, MopPhase.REACTION, MopPhase.IDLE}


def test_max_mops_per_session():
    reset_mop_sessions()
    state = get_mop_session("s6")
    state.mop_count_session = MAX_MOPS_PER_SESSION
    inp = _inp("Lucu banget tadi")
    bdv = decide(inp)
    bdv = bdv.model_copy(update={"engagement_level": 0.9})
    elig = evaluate_mop_eligibility(
        inp=inp,
        bdv=bdv,
        experience_mode="mop",
        session=state,
    )
    assert elig.eligible is False
    assert elig.reason == "max_mops_per_session"
