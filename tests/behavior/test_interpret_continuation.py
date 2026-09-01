"""Continuation intent — e.g. standalone 'Lanjut' should invite a reply."""

from __future__ import annotations

from persona_ai.behavior.engine import decide
from persona_ai.behavior.interpret import interpret
from persona_ai.core.types import BehaviorInput, Message, ResponseLength, SpeakAction, TurnHistory


def test_standalone_lanjut_requests_response():
    intent = interpret(Message.from_text("user", "Lanjut."), 80)
    assert "continuation_request" in intent.reason_codes
    assert intent.requires_response is True

    inp = BehaviorInput(
        message=Message.from_text("user", "Lanjut."),
        history=TurnHistory(
            last_speaker="assistant",
            last_assistant_word_count=80,
            last_assistant_verbosity=ResponseLength.EXPAND,
        ),
    )
    assert decide(inp).speak == SpeakAction.RESPOND


def test_lanjut_ellipsis_not_marked_incomplete():
    intent = interpret(Message.from_text("user", "Lanjut..."), 80)
    assert "continuation_request" in intent.reason_codes
    assert intent.incompleteness_score < 0.5
    assert intent.requires_response is True
