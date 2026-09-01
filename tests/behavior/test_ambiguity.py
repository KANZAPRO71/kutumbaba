"""Ambiguity & mixed-intent stress tests."""

from persona_ai.behavior.engine import decide
from persona_ai.core.types import BehaviorInput, Message, ResponseLength, SpeakAction, TurnHistory


def _speak(text: str, last_assistant_words: int = 0) -> SpeakAction:
    return decide(
        BehaviorInput(
            message=Message.from_text("user", text),
            history=TurnHistory(
                last_assistant_word_count=last_assistant_words,
                last_assistant_verbosity=ResponseLength.EXPAND if last_assistant_words >= 40 else ResponseLength.NORMAL,
            ),
        )
    ).speak


class TestMixedEmotionQuestion:
    def test_vent_plus_question_responds(self):
        assert _speak("ya capek sih tapi besok harus gimana ya") == SpeakAction.RESPOND

    def test_not_defer_on_mixed(self):
        bdv = decide(BehaviorInput(message=Message.from_text("user", "ya capek sih tapi besok harus gimana ya")))
        assert bdv.speak != SpeakAction.DEFER


class TestTrailingConfusion:
    def test_ok_but_confused_responds(self):
        assert _speak("oke deh… tapi sebenarnya aku masih bingung") == SpeakAction.RESPOND

    def test_unicode_ellipsis_trailing_defer(self):
        assert _speak("Hmm… sebenarnya…") == SpeakAction.DEFER


class TestIndirectInstruction:
    def test_pivot_plus_explain_responds(self):
        text = "Jangan terlalu formal ya — wait actually explain the budget thing properly"
        assert _speak(text) == SpeakAction.RESPOND


class TestFrustratedDismissal:
    def test_yaudah_gapapa_not_hard_silence(self):
        action = _speak("yaudah gapapa lah")
        assert action in (SpeakAction.ACK_ONLY, SpeakAction.RESPOND)
        assert action != SpeakAction.SILENCE

    def test_yaudah_gapapa_prefers_ack_over_respond(self):
        assert _speak("yaudah gapapa lah") == SpeakAction.ACK_ONLY

    def test_gapapa_alone_not_false_question(self):
        action = _speak("gapapa")
        assert action == SpeakAction.ACK_ONLY
        assert action != SpeakAction.RESPOND


class TestContradictorySignals:
    def test_short_ack_still_silence_after_long(self):
        assert _speak("Oke", last_assistant_words=200) == SpeakAction.SILENCE

    def test_mixed_beats_pure_vent(self):
        bdv = decide(BehaviorInput(message=Message.from_text("user", "capek banget tapi gimana ya caranya")))
        assert bdv.speak == SpeakAction.RESPOND
