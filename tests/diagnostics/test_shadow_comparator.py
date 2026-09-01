"""Shadow comparison dashboard tests."""

import json
from pathlib import Path

from persona_ai.diagnostics.fingerprint_learning import FingerprintPatchLearner
from persona_ai.diagnostics.shadow_comparator import (
    DomainMetrics,
    ShadowComparator,
    classify_comparison,
    format_shadow_report,
)


class TestClassification:
    def test_overfit_when_sim_much_higher(self):
        sim = DomainMetrics(success_rate=1.0, attempts=5)
        prod = DomainMetrics(success_rate=0.5, occurrences=5)
        assert classify_comparison(0.5, sim=sim, prod=prod) == "simulation_overfit"

    def test_validated_when_close(self):
        sim = DomainMetrics(success_rate=0.8, attempts=5)
        prod = DomainMetrics(success_rate=0.75, occurrences=5)
        assert classify_comparison(0.05, sim=sim, prod=prod) == "validated"

    def test_noise_on_low_frequency(self):
        sim = DomainMetrics(success_rate=1.0, attempts=1)
        prod = DomainMetrics(success_rate=0.0, occurrences=1)
        assert classify_comparison(1.0, sim=sim, prod=prod) == "noise"


class TestShadowComparator:
    def test_end_to_end_with_stores(self, tmp_path):
        learn_path = tmp_path / "learn.json"
        ingest_path = tmp_path / "ingest.json"

        real_fp = "fp_x"
        ingest_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": [
                        {
                            "session_id": sid,
                            "timestamp": "2026-01-01T00:00:00+00:00",
                            "source": "smoke",
                            "context": "sarcasm_stack",
                            "fingerprints": [
                                {
                                    "fp_id": real_fp,
                                    "patch_suggestion": None,
                                    "decayed_score": None,
                                    "raw_score": None,
                                    "context": "sarcasm_stack",
                                    "outcome": "observed_failure",
                                    "turn_index": 0,
                                    "semantic_key": "FP::BDV_UNDER_RESPONSIVE::GENERIC::TEMPLATE_BYPASS",
                                }
                            ],
                            "system_snapshot": {"affects_runtime": False},
                            "contract_pass_rate": 1.0,
                            "readiness_score": 80.0,
                        }
                        for sid in ("prod-1", "prod-2", "prod-3", "prod-4", "prod-5")
                    ],
                }
            ),
            encoding="utf-8",
        )

        learner = FingerprintPatchLearner(learn_path)
        for _ in range(3):
            learner.record_simulation(real_fp, "raise_intent_need", fixes_failure=True)
        learner.save()

        shadow = ShadowComparator(learning_path=learn_path, ingest_path=ingest_path).build_report()
        match = next(c for c in shadow.comparisons if c.fp_id == real_fp)
        assert match.simulation.success_rate == 1.0
        assert match.production.success_rate == 0.0
        assert match.classification == "simulation_overfit"
        assert match.delta.success_gap > 0.3
        assert "Panel B" in format_shadow_report(shadow)
        assert shadow.affects_runtime is False

    def test_no_write_back(self, tmp_path):
        learn_path = tmp_path / "learn.json"
        ingest_path = tmp_path / "ingest.json"
        learner = FingerprintPatchLearner(learn_path)
        learner.record_simulation("fp_x", "patch_a", fixes_failure=True)
        learner.save()
        before = json.loads(learn_path.read_text())

        ShadowComparator(learning_path=learn_path, ingest_path=ingest_path).build_report()
        after = json.loads(learn_path.read_text())
        assert before == after
