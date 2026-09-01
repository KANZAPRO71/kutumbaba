"""Fixed scenario set for Persona A/B social-intelligence experiment."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalScenario:
    scenario_id: str
    description: str
    metrics: tuple[str, ...]
    user_turns: tuple[str, ...]
    seed_assistant_text: str | None = None
    treatment_turn_kwargs: tuple[tuple[str, dict[str, object]], ...] = ()


LONG_ASSISTANT_FILLER = " ".join(["detail"] * 120)


SCENARIOS: tuple[EvalScenario, ...] = (
    EvalScenario(
        scenario_id="closure_after_long",
        description='User says "Oke" after a long assistant answer',
        metrics=("closure", "timing", "intrusiveness"),
        user_turns=("Oke",),
        seed_assistant_text=LONG_ASSISTANT_FILLER,
    ),
    EvalScenario(
        scenario_id="emotional_vent",
        description="User vents without asking for a fix",
        metrics=("vent", "solutionizing", "emotional_fit"),
        user_turns=("Ah capek banget hari ini ya...",),
    ),
    EvalScenario(
        scenario_id="unfinished_thought",
        description="User stops mid-sentence",
        metrics=("pause", "defer", "timing"),
        user_turns=("Jadi rencananya...",),
        treatment_turn_kwargs=(("Jadi rencananya...", {"voice_pause_ms": 1200}),),
    ),
    EvalScenario(
        scenario_id="direct_factual_question",
        description="Direct factual question",
        metrics=("direct_question", "response_correctness"),
        user_turns=("Besok meeting jam berapa?",),
    ),
    EvalScenario(
        scenario_id="mixed_emotion_question",
        description="Mixed vent and question",
        metrics=("mixed_intent", "emotional_fit", "response_correctness"),
        user_turns=("ya capek sih tapi besok harus gimana ya",),
    ),
    EvalScenario(
        scenario_id="dismissive_response",
        description="Dismissive short reply",
        metrics=("closure", "intrusiveness"),
        user_turns=("yaudah gapapa lah",),
    ),
    EvalScenario(
        scenario_id="tone_switch",
        description="User shifts from casual to serious",
        metrics=("tone_switch", "identity_stability"),
        user_turns=(
            "Halo!",
            "Anyway — aku bener-bener khawatir soal deadline besok.",
        ),
    ),
    EvalScenario(
        scenario_id="repeated_short_ack",
        description="Repeated short acknowledgements",
        metrics=("closure", "unnecessary_continuation"),
        user_turns=("Oke", "Sip", "Noted"),
        seed_assistant_text=LONG_ASSISTANT_FILLER,
    ),
    EvalScenario(
        scenario_id="ambiguous_instruction",
        description="Indirect instruction with pivot",
        metrics=("ambiguity", "response_correctness"),
        user_turns=(
            "Jangan terlalu formal ya — wait actually explain the budget thing properly",
        ),
    ),
    EvalScenario(
        scenario_id="long_session_arc",
        description="15+ turn conversation arc",
        metrics=("long_session", "identity_stability", "naturalness"),
        user_turns=(
            "Halo",
            "Aku lagi pusing nih",
            "Kerjaan numpuk",
            "Tapi besok ada meeting penting",
            "Jam berapa ya biasanya standup?",
            "Oke",
            "Btw aku juga khawatir soal budget",
            "Tapi ya sudahlah",
            "Thanks",
            "Oke",
            "Sip",
            "Noted",
            "Hmm",
            "Ya sudah deh",
            "Oke",
        ),
    ),
)

SCENARIO_BY_ID = {scenario.scenario_id: scenario for scenario in SCENARIOS}
