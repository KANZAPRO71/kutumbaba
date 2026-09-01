"""Explainability dashboard v1 tests."""

import json
from datetime import datetime, timezone

from persona_ai.diagnostics.explainability_dashboard import (
    ContractTelemetryRecord,
    ExplainabilityDashboard,
    ExplainabilityTelemetryStore,
    build_run_snapshot,
    persist_run_records,
    record_from_decomposition,
)
from persona_ai.diagnostics.fast_path_controller import compute_S_final


class TestTelemetryStore:
    def test_persist_and_reload(self, tmp_path):
        path = tmp_path / "telemetry.json"
        records = [
            record_from_decomposition(
                compute_S_final(
                    raw_score=0.82,
                    learned_score=0.75,
                    elasticity_weight=1.0,
                    decay_factor=1.0,
                    trust_state="active",
                ),
                fp_id="fp_a",
                patch_id="patch_x",
            )
        ]
        persist_run_records(records, script_name="test", store=ExplainabilityTelemetryStore(path))

        reloaded = ExplainabilityTelemetryStore(path)
        assert len(reloaded.snapshots) == 1
        assert reloaded.snapshots[0].contract_pass_rate == 1.0

    def test_violation_snapshot(self, tmp_path):
        path = tmp_path / "telemetry.json"
        decomp = compute_S_final(
            raw_score=0.82,
            learned_score=0.75,
            elasticity_weight=1.0,
            decay_factor=1.0,
            trust_state="active",
        )
        decomp.s_final = 0.5
        decomp.contract_valid = False
        rec = ContractTelemetryRecord(
            fp_id="fp_bad",
            patch_id="p1",
            s_final=0.5,
            contract_valid=False,
            reconstruction_delta=0.3,
            scoring_surface_version="S_final_v1",
            trust_state="active",
            violation_codes=["RECONSTRUCTION_MISMATCH"],
            fast_path_eligible=False,
        )
        persist_run_records([rec], store=ExplainabilityTelemetryStore(path))
        snap = ExplainabilityTelemetryStore(path).snapshots[0]
        assert snap.violation_count == 1
        assert snap.contract_pass_rate == 0.0


class TestDashboardReport:
    def test_healthy_report(self, tmp_path):
        path = tmp_path / "telemetry.json"
        store = ExplainabilityTelemetryStore(path)
        records = [
            record_from_decomposition(
                compute_S_final(
                    raw_score=0.85,
                    learned_score=0.80,
                    elasticity_weight=1.0,
                    decay_factor=1.0,
                    trust_state="active",
                ),
                fp_id="fp_ok",
                patch_id="p1",
            )
        ]
        store.append_snapshot(build_run_snapshot(records, script_name="semantic_chaos"))

        report = ExplainabilityDashboard(store, promoted_store=None).build_report(include_live=False)
        assert report.contract_pass_rate == 1.0
        assert report.violation_rate == 0.0
        assert "HEALTHY" in report.debug_trace
        assert "Panel B" in report.debug_trace

    def test_violation_surfaces_in_dashboard(self, tmp_path):
        path = tmp_path / "telemetry.json"
        store = ExplainabilityTelemetryStore(path)
        store.append_snapshot(
            build_run_snapshot(
                [
                    ContractTelemetryRecord(
                        fp_id="fp_v",
                        patch_id="p1",
                        s_final=0.4,
                        contract_valid=False,
                        reconstruction_delta=0.2,
                        scoring_surface_version="S_final_v1",
                        trust_state="active",
                        violation_codes=["RECONSTRUCTION_MISMATCH"],
                        fast_path_eligible=False,
                    )
                ],
                script_name="sarcasm_stack",
            )
        )
        report = ExplainabilityDashboard(store).build_report(include_live=False)
        assert report.violation_rate > 0
        assert "VIOLATIONS_DETECTED" in report.debug_trace
        assert "fp_v" in report.fingerprint_violations
