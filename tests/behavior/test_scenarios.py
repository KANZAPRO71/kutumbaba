"""Behavior scenario tests — BEHAVIOR_ENGINE §11 / ROADMAP v0 exit criteria."""

from persona_ai.behavior.engine import decide, execution_profile
from persona_ai.core.types import (
    BehaviorInput,
    Message,
    ResponseLength,
    SpeakAction,
    TurnHistory,
)
from persona_ai.coherence.bind import bind
from persona_ai.core.types import IdentityAnchor, PersonalityProfile
from persona_ai.personality.apply import apply


def _decide(text: str, last_assistant_words: int = 0) -> SpeakAction:
    inp = BehaviorInput(
        message=Message.from_text("user", text),
        history=TurnHistory(
            last_speaker="assistant" if last_assistant_words else "user",
            last_assistant_word_count=last_assistant_words,
            last_assistant_verbosity=ResponseLength.EXPAND if last_assistant_words >= 40 else ResponseLength.NORMAL,
        ),
    )
    return decide(inp).speak


class TestScenarioA_Vent:
    def test_vent_is_ack_not_full_respond(self):
        action = _decide("Ah capek banget hari ini ya...")
        assert action == SpeakAction.ACK_ONLY

    def test_whisper_profile(self):
        inp = BehaviorInput(message=Message.from_text("user", "Ah capek banget hari ini ya..."))
        bdv = decide(inp)
        assert execution_profile(bdv) == "whisper"
        expr = apply(PersonalityProfile(), bdv, execution_profile=execution_profile(bdv))
        assert expr.template_ack is None


class TestScenarioB_Closure:
    def test_oke_after_long_assistant_is_silence(self):
        action = _decide("Oke", last_assistant_words=200)
        assert action == SpeakAction.SILENCE

    def test_early_exit_no_llm(self):
        inp = BehaviorInput(
            message=Message.from_text("user", "Oke"),
            history=TurnHistory(last_assistant_word_count=200, last_assistant_verbosity=ResponseLength.EXPAND),
        )
        bdv = decide(inp)
        assert bdv.is_early_exit
        assert not bdv.requires_llm


class TestScenarioC_Defer:
    def test_mid_thought_defer(self):
        inp = BehaviorInput(
            message=Message.from_text("user", "Jadi rencananya..."),
            voice_pause_ms=1200,
        )
        assert decide(inp).speak == SpeakAction.DEFER


class TestScenarioD_DirectQuestion:
    def test_direct_question_responds(self):
        action = _decide("Besok meeting jam berapa?")
        assert action == SpeakAction.RESPOND

    def test_direct_question_does_not_spend_question_budget(self):
        inp = BehaviorInput(message=Message.from_text("user", "Besok meeting jam berapa?"))
        bdv = decide(inp)
        assert bdv.speak == SpeakAction.RESPOND
        assert bdv.requires_llm
        assert bdv.question_budget == 0
        expr = apply(PersonalityProfile(), bdv)
        assert "ada yang mau ditanyakan" in " ".join(expr.prompt_fragments)


class TestScenarioGreeting:
    def test_halo_responds(self):
        assert _decide("Halo.") == SpeakAction.RESPOND

    def test_selamat_pagi_responds(self):
        assert _decide("Selamat pagi") == SpeakAction.RESPOND


class TestCoherenceFloor:
    def test_warmth_clamped_not_flat_zero(self):
        inp = BehaviorInput(message=Message.from_text("user", "Ah capek banget..."))
        bdv = decide(inp)
        profile = PersonalityProfile(warmth=0.65)
        expr = apply(profile, bdv)
        voice = bind(bdv, expr, profile)
        assert voice.effective_warmth >= 0.45
        assert bdv.question_budget == 0

    def test_bdv_speak_unchanged_after_coherence(self):
        inp = BehaviorInput(message=Message.from_text("user", "Besok jam berapa?"))
        bdv = decide(inp)
        voice = bind(bdv, apply(PersonalityProfile(), bdv), PersonalityProfile())
        assert voice.speak == bdv.speak
