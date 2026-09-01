"""Live voice response policy — no dead-air after user speaks."""

from __future__ import annotations

from persona_ai.behavior.engine import decide
from persona_ai.core.types import BehaviorInput, Message, SpeakAction
from persona_ai.runtime import _apply_live_voice_policy


def test_live_voice_upgrades_defer_to_respond():
    inp = BehaviorInput(message=Message.from_text("user", "Hmm jadi"))
    raw = decide(inp)
    assert raw.speak == SpeakAction.DEFER
    effective = _apply_live_voice_policy(raw)
    assert effective.speak == SpeakAction.RESPOND


def test_natural_voice_upgrades_ack_to_respond():
    from persona_ai.runtime import _apply_natural_voice_policy

    inp = BehaviorInput(message=Message.from_text("user", "Kita ngobrol soal kamu saja."))
    raw = decide(inp)
    effective = _apply_natural_voice_policy(raw)
    assert effective.speak == SpeakAction.RESPOND


def test_live_voice_upgrades_lanjutkan_to_respond():
    inp = BehaviorInput(message=Message.from_text("user", "Lanjutkan."))
    raw = decide(inp)
    effective = _apply_live_voice_policy(raw)
    assert effective.speak == SpeakAction.RESPOND


def test_should_govern_transcript_skips_filler():
    from persona_ai.web.gemini_live_bridge import _should_govern_transcript

    assert not _should_govern_transcript("Hmm.")
    assert not _should_govern_transcript("and dengan")
    assert _should_govern_transcript("Bro.")
    assert _should_govern_transcript("Ya.")
    assert _should_govern_transcript("apa")
    assert _should_govern_transcript("Kenapa suaramu hilang-hilang?")
    assert _should_govern_transcript("Jelaskan tentang AI.")
