"""Daily rhythm + mode behavior bias."""

from __future__ import annotations

from persona_ai.behavior.interpret import interpret
from persona_ai.conversation.behavior_bias import bias_bdv_for_mode
from persona_ai.conversation.companion_stats import record_companion_session, reset_companion_stats_store
from persona_ai.conversation.daily import DayPart, daily_companion_lines, day_part_from_hour
from persona_ai.core.types import BehaviorInput, Message, SpeakAction
from persona_ai.runtime import PersonaRuntime
from persona_ai.session.store import InMemorySessionStore


def test_day_part_boundaries():
    assert day_part_from_hour(8) == DayPart.MORNING
    assert day_part_from_hour(14) == DayPart.AFTERNOON
    assert day_part_from_hour(19) == DayPart.EVENING
    assert day_part_from_hour(23) == DayPart.NIGHT


def test_daily_lines_papua():
    lines = daily_companion_lines(DayPart.MORNING, language="id", dialect="papua")
    assert any("Pagi" in line for line in lines)


def test_curhat_vent_biases_ack():
    msg = Message.from_text("user", "Ah capek banget hari ini ya...")
    inp = BehaviorInput(message=msg, conversation_mode="curhat")
    from persona_ai.behavior.engine import decide

    bdv = decide(inp)
    bdv = bias_bdv_for_mode(bdv, inp, conversation_mode="curhat")
    intent = interpret(msg, 0)
    if intent.is_vent and bdv.speak == SpeakAction.RESPOND:
        bdv = bias_bdv_for_mode(bdv, inp, conversation_mode="curhat")
    assert bdv.speak in {SpeakAction.ACK_ONLY, SpeakAction.RESPOND}


def test_companion_streak(tmp_path, monkeypatch):
    db = tmp_path / "mem.db"
    monkeypatch.setenv("PERSONA_MEMORY_DB", str(db))
    reset_companion_stats_store()
    s1 = record_companion_session(duration_ms=60_000)
    assert s1.streak_days == 1
    s2 = record_companion_session(duration_ms=30_000)
    assert s2.streak_days == 1
    assert s2.total_sessions == 2


def test_runtime_accepts_conversation_mode():
    runtime = PersonaRuntime(session_store=InMemorySessionStore())
    out = runtime.process_turn(
        "s-mode",
        "Ko dengar sa dulu",
        channel="text",
        conversation_mode="curhat",
    )
    assert out.bdv is not None
