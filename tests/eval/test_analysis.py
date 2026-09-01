"""Analysis tests — governance win rate and per-scenario breakdown."""

from __future__ import annotations

from persona_ai.eval.analysis import (
    analyze_experiment,
    persona_governance_applied,
    reviewer_prefers_treatment,
)


class TestGovernanceWinRate:
    def test_governance_applied_on_silence(self):
        row = {"scenario_id": "closure", "bdv": "SILENCE", "control_text": "x", "treatment_text": None}
        assert persona_governance_applied(row) is True

    def test_governance_not_applied_on_respond(self):
        row = {
            "scenario_id": "q",
            "bdv": "RESPOND",
            "control_text": "a",
            "treatment_text": "b",
            "treatment_llm_called": True,
        }
        assert persona_governance_applied(row) is False

    def test_reviewer_preference_mapping(self):
        assert reviewer_prefers_treatment("A", a_is_treatment=True) is True
        assert reviewer_prefers_treatment("B", a_is_treatment=True) is False
        assert reviewer_prefers_treatment("tie", a_is_treatment=True) is False

    def test_governance_win_rate_computation(self):
        scenarios = [
            {"scenario_id": "closure", "bdv": "SILENCE", "control_text": "long", "treatment_text": None},
            {"scenario_id": "question", "bdv": "RESPOND", "control_text": "a", "treatment_text": "b", "treatment_llm_called": True},
        ]
        manifest = {
            "p1": {"pair_id": "p1", "scenario_id": "closure", "a_is_treatment": True},
            "p2": {"pair_id": "p2", "scenario_id": "closure", "a_is_treatment": False},
        }
        scores = [
            {"pair_id": "p1", "scenario_id": "closure", "preference": "A"},
            {"pair_id": "p2", "scenario_id": "closure", "preference": "B"},
        ]
        analysis = analyze_experiment(scenarios, scores, manifest)
        assert analysis["governance_win_rate"]["wins"] == 2
        assert analysis["governance_win_rate"]["total_judgments"] == 2
        assert analysis["governance_win_rate"]["rate"] == 1.0
        assert analysis["overall_preference"]["wins"] == 2
        assert analysis["overall_preference"]["total_judgments"] == 2
        assert analysis["per_scenario"]["closure"]["preference"]["treatment"] == 2
