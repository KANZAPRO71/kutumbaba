"""Fingerprint patch learning + confidence decay tests."""

from datetime import datetime, timedelta, timezone

import pytest

from persona_ai.diagnostics.fingerprint_learning import (
    DecayedPatchView,
    FingerprintPatchLearner,
    FingerprintPatchStats,
    decay_factor,
    ingest_lifecycle_outcomes,
)
from persona_ai.diagnostics.regression_dashboard import FingerprintLifecycle
from tests.support.stub_llm import StubLLMAdapter
from persona_ai.sim.smoke_openai import run_smoke


def _fixed_clock(start: datetime):
    state = {"t": start}

    def tick():
        return state["t"]

    def advance(days: float) -> None:
        state["t"] = state["t"] + timedelta(days=days)

    return tick, advance


class TestDecayFactor:
    def test_fresh_stats_no_decay(self):
        now = datetime(2026, 8, 26, tzinfo=timezone.utc)
        ts = now.isoformat()
        assert decay_factor(ts, now=now) == pytest.approx(1.0, abs=0.01)

    def test_half_life_reduces_weight(self):
        now = datetime(2026, 8, 26, tzinfo=timezone.utc)
        then = (now - timedelta(days=10)).isoformat()
        assert decay_factor(then, now=now, half_life_days=10.0) == pytest.approx(0.5, abs=0.02)


class TestDecayedPatchView:
    def test_stale_high_score_falls_below_fast_path(self):
        stats = FingerprintPatchStats(attempts=3, success=3, regressions=0)
        fresh = datetime(2026, 8, 26, tzinfo=timezone.utc)
        stats.last_updated = fresh.isoformat()
        stale_now = fresh + timedelta(days=30)
        view = DecayedPatchView.from_stats(stats, now=stale_now, half_life_days=10.0)
        assert view.raw_score == 1.0
        assert view.decayed_score == pytest.approx(1.0, abs=0.01)
        assert view.effective_attempts < 2.0

    def test_regression_spike_penalty(self):
        stats = FingerprintPatchStats(attempts=3, success=3, regressions=1)
        now = datetime(2026, 8, 26, tzinfo=timezone.utc)
        stats.last_updated = now.isoformat()
        view = DecayedPatchView.from_stats(stats, now=now, half_life_days=10.0)
        assert view.decayed_score < view.raw_score


class TestFingerprintPatchLearner:
    def test_fast_path_uses_effective_attempts(self, tmp_path):
        start = datetime(2026, 8, 26, tzinfo=timezone.utc)
        clock, advance = _fixed_clock(start)
        learner = FingerprintPatchLearner(tmp_path / "fp.json", clock=clock)
        learner.record_simulation("fp_x", "patch_a", fixes_failure=True)
        learner.record_simulation("fp_x", "patch_a", fixes_failure=True)
        preds = learner.predict_best("fp_x", ["patch_a"])
        assert learner.fast_path_eligible(preds[0])

        advance(30)
        preds_stale = learner.predict_best("fp_x", ["patch_a"])
        assert not learner.fast_path_eligible(preds_stale[0])

    def test_persistence_includes_last_updated(self, tmp_path):
        start = datetime(2026, 8, 26, tzinfo=timezone.utc)
        clock, _ = _fixed_clock(start)
        path = tmp_path / "fp.json"
        l1 = FingerprintPatchLearner(path, clock=clock)
        l1.record_simulation("fp_a", "patch_b", fixes_failure=True)
        l1.save()
        l2 = FingerprintPatchLearner(path, clock=clock)
        assert l2._store["fp_a"]["patch_b"].last_updated


class TestLifecycleIngest:
    def test_closed_credits_success(self, tmp_path):
        learner = FingerprintPatchLearner(tmp_path / "fp.json")
        lifecycle = FingerprintLifecycle(closed=["fp_a"])
        ingest_lifecycle_outcomes(
            learner,
            lifecycle=lifecycle,
            previous_recommended={"fp_a": "raise_intent_need"},
        )
        stats = learner._store["fp_a"]["raise_intent_need"]
        assert stats.success == 1
        assert stats.last_updated

    def test_regression_increments_penalty(self, tmp_path):
        learner = FingerprintPatchLearner(tmp_path / "fp.json")
        learner.record_simulation("fp_a", "patch_x", fixes_failure=True)
        learner.record_simulation("fp_a", "patch_x", fixes_failure=True)
        lifecycle = FingerprintLifecycle(regressions=["fp_a"])
        ingest_lifecycle_outcomes(
            learner,
            lifecycle=lifecycle,
            previous_recommended={"fp_a": "patch_x"},
        )
        stats = learner._store["fp_a"]["patch_x"]
        view = DecayedPatchView.from_stats(stats, half_life_days=learner.half_life_days)
        assert stats.regressions == 1
        assert view.decayed_score < view.raw_score


class TestSmokeStability:
    def test_fresh_learning_still_predicts_on_sarcasm_stack(self):
        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        lr = report.failure.intervention_learning
        assert not lr.fingerprint_recommendations
        assert not lr.predictions
