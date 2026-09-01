"""Multi-turn drift stress tests — identity stability across 15–30 turns."""

import pytest

from persona_ai.core.types import PersonalityProfile, SpeakAction
from persona_ai.sim.drift_harness import SessionSimulator, compute_drift_metrics
from persona_ai.sim.scripts import SCRIPTS


@pytest.fixture
def profile() -> PersonalityProfile:
    return PersonalityProfile(warmth=0.6, formality=0.3)


class TestAnchorPersistence:
    def test_anchor_updates_across_turns(self, profile: PersonalityProfile):
        sim = SessionSimulator("anchor-test", profile=profile)
        sim.run_turn("Halo")
        baseline_after_1 = sim.anchor.session_tone_baseline
        sim.run_turn("Ah capek banget hari ini ya...")
        assert sim.anchor.session_tone_baseline != baseline_after_1 or sim.turns[-1].effective_warmth > 0.5

    def test_warmth_step_within_coherence_bound(self, profile: PersonalityProfile):
        sim = SessionSimulator("step-test", profile=profile)
        for text in SCRIPTS["chaotic_mixed"][:12]:
            sim.run_turn(text)
        m = compute_drift_metrics(sim.turns, profile)
        assert m.max_warmth_step <= 0.16, m.notes


class TestLongSessionScripts:
    @pytest.mark.parametrize("script_name", list(SCRIPTS.keys()))
    def test_script_completes_without_crash(self, profile: PersonalityProfile, script_name: str):
        sim = SessionSimulator(f"drift-{script_name}", profile=profile)
        report = sim.run_script(script_name, SCRIPTS[script_name])
        assert report.metrics.turn_count == len(SCRIPTS[script_name])
        assert len(report.turns) == len(SCRIPTS[script_name])

    @pytest.mark.parametrize("script_name", list(SCRIPTS.keys()))
    def test_not_grade_c(self, profile: PersonalityProfile, script_name: str):
        """Grade C = mechanical / unstable — fail before production."""
        bootstrap = script_name == "silence_pressure"
        sim = SessionSimulator(
            f"grade-{script_name}",
            profile=profile,
            bootstrap_long_assistant=bootstrap,
        )
        report = sim.run_script(script_name, SCRIPTS[script_name])
        assert report.metrics.grade in ("A", "B"), (
            f"{script_name}: grade={report.metrics.grade} notes={report.metrics.notes}"
        )

    def test_chaotic_mixed_has_behavioral_variety(self, profile: PersonalityProfile):
        sim = SessionSimulator("variety", profile=profile)
        report = sim.run_script("chaotic_mixed", SCRIPTS["chaotic_mixed"])
        actions = {t.speak for t in report.turns}
        assert SpeakAction.RESPOND in actions
        assert SpeakAction.ACK_ONLY in actions or SpeakAction.SILENCE in actions

    def test_silence_pressure_triggers_silence(self, profile: PersonalityProfile):
        sim = SessionSimulator("silence", profile=profile, bootstrap_long_assistant=True)
        report = sim.run_script("silence_pressure", SCRIPTS["silence_pressure"])
        assert report.metrics.speak_counts.get(SpeakAction.SILENCE.value, 0) >= 2


class TestIdentityFloor:
    def test_warmth_never_collapses_to_zero(self, profile: PersonalityProfile):
        sim = SessionSimulator("floor", profile=profile)
        report = sim.run_script("boundary_push", SCRIPTS["boundary_push"])
        assert all(w >= profile.warmth - 0.25 for w in report.metrics.warmth_values)

    def test_bdv_speak_stable_under_tone_switch(self, profile: PersonalityProfile):
        sim = SessionSimulator("tone", profile=profile)
        report = sim.run_script("tone_switching", SCRIPTS["tone_switching"])
        assert report.metrics.warmth_range >= 0.04
        assert report.metrics.max_warmth_step <= 0.16
