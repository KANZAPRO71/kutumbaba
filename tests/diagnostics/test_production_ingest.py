"""Production ingest read-only observer tests."""

import ast
import json
from pathlib import Path

import pytest

from persona_ai.diagnostics.fingerprint_learning import FingerprintPatchLearner
from persona_ai.diagnostics.production_ingest import (
    ProductionIngestor,
    affects_runtime_decision,
    build_ingest_entry,
    classify_turn_outcome,
    production_coverage,
)
from tests.support.stub_llm import StubLLMAdapter
from persona_ai.sim.smoke_openai import run_smoke


class TestGuardrails:
    def test_never_affects_runtime(self):
        assert affects_runtime_decision() is False

    def test_behavior_layer_does_not_import_production_ingest(self):
        behavior_root = Path(__file__).resolve().parents[2] / "src" / "persona_ai" / "behavior"
        for path in behavior_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "production_ingest" not in alias.name
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert "production_ingest" not in node.module


class TestOutcomeClassification:
    def test_contract_pass_is_success(self):
        assert classify_turn_outcome(
            2, contracts_passed={2: True}, cps_score=0.0, had_failure=False
        ) == "observed_success"

    def test_contract_fail_is_failure(self):
        assert classify_turn_outcome(
            2, contracts_passed={2: False}, cps_score=0.0, had_failure=True
        ) == "observed_failure"

    def test_cps_spike_is_degraded(self):
        assert classify_turn_outcome(
            2, contracts_passed={}, cps_score=0.5, had_failure=False
        ) == "degraded"


class TestProductionIngestor:
    def test_observe_does_not_update_learning_store(self, tmp_path):
        log_path = tmp_path / "ingest.json"
        learn_path = tmp_path / "learn.json"
        ingestor = ProductionIngestor(log_path, buffer_size=1)
        learner = FingerprintPatchLearner(learn_path)
        before = learner.store_size

        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        ingestor.observe(report, session_id="sess-1", force_flush=True)

        assert log_path.exists()
        assert learner.store_size == before

    def test_batch_flush_on_buffer_size(self, tmp_path):
        log_path = tmp_path / "ingest.json"
        ingestor = ProductionIngestor(log_path, buffer_size=2, flush_interval_s=9999)
        report = run_smoke("semantic_chaos", StubLLMAdapter())

        ingestor.observe(report, session_id="s1")
        assert not log_path.exists()
        ingestor.observe(report, session_id="s2")
        assert log_path.exists()
        entries = json.loads(log_path.read_text())["entries"]
        assert len(entries) == 2

    def test_fingerprint_first_observations(self, tmp_path):
        ingestor = ProductionIngestor(tmp_path / "ingest.json", buffer_size=1)
        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        entry = ingestor.observe(report, session_id="fp-test", force_flush=True)
        assert entry.fingerprints == []
        assert entry.system_snapshot["affects_runtime"] is False
        assert entry.readiness_score == 100.0

    def test_clean_run_empty_fingerprints(self, tmp_path):
        ingestor = ProductionIngestor(tmp_path / "ingest.json", buffer_size=1)
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        entry = build_ingest_entry(report, session_id="clean")
        assert entry.fingerprints == []
        assert entry.readiness_score == 100.0

    def test_coverage_metrics(self, tmp_path):
        ingestor = ProductionIngestor(tmp_path / "ingest.json", buffer_size=1)
        ingestor.observe(run_smoke("sarcasm_stack", StubLLMAdapter()), session_id="a", force_flush=True)
        ingestor.observe(run_smoke("semantic_chaos", StubLLMAdapter()), session_id="b", force_flush=True)
        cov = production_coverage(ingestor.load_entries())
        assert cov["session_coverage"] == 0.0
        assert cov["unique_fingerprints"] == 0.0
