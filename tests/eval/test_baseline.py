"""Baseline workflow tests — StubLLMAdapter for artifact layout (no Gemini key)."""

from __future__ import annotations

import json

from persona_ai.eval.baseline import (
    TARGET_JUDGMENTS,
    baseline_status,
    prepare_baseline,
)
from persona_ai.eval.human_eval import HumanEvalScores, record_human_eval
from tests.support.stub_llm import StubLLMAdapter


class TestBaselinePrepare:
    def test_prepare_writes_artifacts(self, tmp_path):
        base = tmp_path / "eval"
        paths = {
            "results": base / "ab_results.json",
            "manifest": base / "blind_pairs_manifest.json",
            "forms": base / "reviewer_forms.json",
            "scores": base / "human_scores.jsonl",
            "metadata": base / "baseline_metadata.json",
        }
        summary = prepare_baseline(adapter=StubLLMAdapter(), paths=paths)
        assert summary["scenario_count"] == 10
        assert summary["pair_count"] == 10
        assert paths["results"].is_file()
        assert paths["manifest"].is_file()
        assert paths["forms"].is_file()
        assert paths["metadata"].is_file()

        metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
        assert metadata["experiment"] == "north_star_baseline_v1"
        assert metadata["target_judgments"] == TARGET_JUDGMENTS

        forms = json.loads(paths["forms"].read_text(encoding="utf-8"))
        assert len(forms) == 10
        assert "transcript_a" in forms[0]
        assert "persona" not in json.dumps(forms).lower()


class TestBaselineStatus:
    def test_status_tracks_score_progress(self, tmp_path):
        base = tmp_path / "eval"
        paths = {
            "results": base / "ab_results.json",
            "manifest": base / "blind_pairs_manifest.json",
            "forms": base / "reviewer_forms.json",
            "scores": base / "human_scores.jsonl",
            "metadata": base / "baseline_metadata.json",
        }
        prepare_baseline(adapter=StubLLMAdapter(), paths=paths)

        status = baseline_status(paths=paths)
        assert status["human_scores"]["count"] == 0
        assert status["judgments_remaining"] == TARGET_JUDGMENTS
        assert status["ready_for_analysis"] is False

        record_human_eval(
            HumanEvalScores(
                pair_id="p1",
                scenario_id="closure_after_long",
                naturalness=6,
                timing=7,
                intrusiveness=5,
                emotional_fit=6,
                preference="A",
                reviewer_id="r1",
            ),
            store_path=paths["scores"],
        )
        status = baseline_status(paths=paths)
        assert status["human_scores"]["count"] == 1
        assert status["human_scores"]["unique_reviewers"] == 1
