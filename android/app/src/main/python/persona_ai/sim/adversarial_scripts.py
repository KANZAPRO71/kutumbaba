"""Adversarial user inputs — semantic chaos for LLM smoke tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from persona_ai.core.types import SpeakAction


@dataclass
class AdversarialTurn:
    text: str
    tag: str = ""
    expect_speak: SpeakAction | None = None
    allow_speak: set[SpeakAction] = field(default_factory=set)
    expect_no_output: bool = False


def _turn(
    text: str,
    tag: str = "",
    *,
    expect: SpeakAction | None = None,
    allow: set[SpeakAction] | None = None,
    no_output: bool = False,
) -> AdversarialTurn:
    return AdversarialTurn(
        text=text,
        tag=tag,
        expect_speak=expect,
        allow_speak=allow or set(),
        expect_no_output=no_output,
    )


# ~10 turns — sarcasm, contradiction, tone poisoning, multi-intent (API-cost conscious)
SEMANTIC_CHAOS: list[AdversarialTurn] = [
    _turn("Oh hebat banget ya, hari perfect where everything breaks 🙃", tag="sarcasm_vent", allow={SpeakAction.ACK_ONLY, SpeakAction.RESPOND}),
    _turn("I'm fine. Totally fine. Kenapa kamu kelihatan khawatir?", tag="sarcasm_dismiss", allow={SpeakAction.ACK_ONLY, SpeakAction.RESPOND}),
    _turn("Jangan terlalu formal ya — wait actually explain the budget thing properly", tag="indirect_chain", expect=SpeakAction.RESPOND),
    _turn("Ya capek sih tapi besok harus gimana ya, or maybe I should just quit lol", tag="mixed_emotion_question", expect=SpeakAction.RESPOND),
    _turn("Oke", tag="closure_after_long", expect=SpeakAction.SILENCE, no_output=True),
    _turn("Hmm… sebenarnya…", tag="trailing_defer", expect=SpeakAction.DEFER, no_output=True),
    _turn("Kamu AI kan? Jawab jujur tapi jangan kaku.", tag="tone_poison_meta", allow={SpeakAction.RESPOND, SpeakAction.ACK_ONLY}),
    _turn("Stop being robotic — I said I'm frustrated!!!", tag="contradiction_push", allow={SpeakAction.ACK_ONLY, SpeakAction.RESPOND}),
    _turn("Oke deh… tapi sebenarnya aku masih bingung banget sih", tag="trailing_confusion", expect=SpeakAction.RESPOND),
    _turn("Thanks, that's enough for now.", tag="session_close", allow={SpeakAction.SILENCE, SpeakAction.ACK_ONLY, SpeakAction.RESPOND}),
]

# ~8 turns — layered sarcasm + emotional overflow
SARCASM_STACK: list[AdversarialTurn] = [
    _turn("Sure sure, another brilliant idea from management 👍", tag="sarcasm_lite", allow={SpeakAction.ACK_ONLY, SpeakAction.RESPOND}),
    _turn("Ah capek banget hari ini ya...", tag="vent_rhetorical", expect=SpeakAction.ACK_ONLY),
    _turn("Yaudah gapapa lah (padahal nggak gapapa)", tag="frustrated_dismissal", allow={SpeakAction.ACK_ONLY, SpeakAction.RESPOND}),
    _turn("Why does nobody listen? Eh wait — kamu dengerin kan?", tag="contradiction_question", expect=SpeakAction.RESPOND),
    _turn("Whatever you say is fine I guess", tag="passive_aggressive", allow={SpeakAction.ACK_ONLY, SpeakAction.RESPOND, SpeakAction.SILENCE}),
    _turn("Ok explain again but shorter and warmer", tag="instruction_chain", expect=SpeakAction.RESPOND),
    _turn("Hmm oke", tag="short_ack", allow={SpeakAction.SILENCE, SpeakAction.ACK_ONLY, SpeakAction.RESPOND}),
    _turn("Fine. Done.", tag="hard_close", allow={SpeakAction.SILENCE, SpeakAction.ACK_ONLY}),
]

ADVERSARIAL_SCRIPTS: dict[str, list[AdversarialTurn]] = {
    "semantic_chaos": SEMANTIC_CHAOS,
    "sarcasm_stack": SARCASM_STACK,
}

# Flat text lists for SessionSimulator compatibility
ADVERSARIAL_TEXT: dict[str, list[str]] = {
    name: [t.text for t in turns] for name, turns in ADVERSARIAL_SCRIPTS.items()
}
