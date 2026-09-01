"""Manifold CI axiom lock tests."""

from pathlib import Path

from persona_ai.diagnostics.manifold_ci import (
    ManifoldExit,
    build_canonical_fixture,
    check_constraint_arbitration,
    check_cross_cluster_sanity,
    check_explainability_contract,
    check_geometry_ci_gate,
    check_shadow_drift_regression,
    run_manifold_ci,
)


class TestManifoldCI:
    def test_canonical_fixture_builds(self):
        fixture = build_canonical_fixture()
        assert len(fixture.cross_results) == 3
        assert len(fixture.decomps) == 3
        assert fixture.geometry_gate is not None
        assert fixture.arbitration is not None

    def test_geometry_gate_passes(self):
        result = check_geometry_ci_gate()
        assert result.status == "PASS"
        assert result.exit_code == ManifoldExit.PASS

    def test_arbitration_feasible(self):
        result = check_constraint_arbitration()
        assert result.status == "PASS"

    def test_explainability_verify(self):
        result = check_explainability_contract()
        assert result.status == "PASS"

    def test_cross_cluster_sanity(self):
        result = check_cross_cluster_sanity()
        assert result.status == "PASS"

    def test_drift_regression_skips_without_history(self):
        result = check_shadow_drift_regression(alerts_path=Path("/nonexistent/drift_alerts.json"))
        assert result.status == "SKIP"

    def test_full_pipeline_passes(self):
        report = run_manifold_ci()
        assert report.passed
        assert report.exit_code == 0
        assert len(report.steps) == 5

    def test_exit_code_mapping(self):
        report = run_manifold_ci()
        blocking = [s for s in report.steps if s.status in ("BLOCKED", "INFEASIBLE", "VIOLATION")]
        if blocking:
            assert report.exit_code == blocking[0].exit_code
        else:
            assert report.exit_code == 0
