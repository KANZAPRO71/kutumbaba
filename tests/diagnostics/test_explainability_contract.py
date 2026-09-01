"""Explainability contract v1 tests."""

import pytest

from persona_ai.diagnostics.explainability_contract import (
    RECONSTRUCTION_EPSILON,
    SCORING_COEFFICIENTS,
    SCORING_SURFACE_VERSION,
    ExplainabilityContractError,
    assert_explainability_contract,
    detect_coefficient_drift,
    reconstruct_s_final,
    verify_explainability_contract,
)
from persona_ai.diagnostics.fast_path_controller import ScoreDecomposition, compute_S_final


def _sample_decomp(**overrides) -> ScoreDecomposition:
    base = compute_S_final(
        raw_score=0.82,
        learned_score=0.75,
        elasticity_weight=0.9,
        decay_factor=0.95,
        trust_state="active",
        effective_attempts=3.0,
    )
    if overrides:
        data = base.to_dict()
        data.update(overrides)
        return ScoreDecomposition(**{k: data[k] for k in ScoreDecomposition.__dataclass_fields__})
    return base


class TestReconstructionInvariant:
    def test_valid_decomposition_passes(self):
        decomp = _sample_decomp()
        verdict = verify_explainability_contract(decomp)
        assert verdict.valid
        assert verdict.reconstruction_delta <= RECONSTRUCTION_EPSILON
        assert verdict.scoring_surface_version == SCORING_SURFACE_VERSION

    def test_reconstruct_matches_s_final(self):
        decomp = _sample_decomp()
        assert reconstruct_s_final(decomp) == decomp.s_final

    def test_demoted_reconstruction(self):
        decomp = compute_S_final(
            raw_score=0.9,
            learned_score=0.9,
            elasticity_weight=1.0,
            decay_factor=1.0,
            trust_state="demoted",
        )
        verdict = verify_explainability_contract(decomp)
        assert verdict.valid
        assert decomp.s_final == 0.0

    def test_tampered_s_final_fails(self):
        decomp = _sample_decomp(s_final=0.999)
        verdict = verify_explainability_contract(decomp)
        assert not verdict.valid
        assert any(v.code == "RECONSTRUCTION_MISMATCH" for v in verdict.violations)

    def test_assert_raises_on_violation(self):
        decomp = _sample_decomp(pre_decay=0.5)
        with pytest.raises(ExplainabilityContractError):
            assert_explainability_contract(decomp)


class TestCoefficientRegistry:
    def test_frozen_registry_present(self):
        assert "S_final_v1" in SCORING_COEFFICIENTS
        assert SCORING_COEFFICIENTS["S_final_v1"]["learned_blend"] == 0.5

    def test_no_drift_within_same_version(self):
        violations = detect_coefficient_drift("S_final_v1", "S_final_v1")
        assert violations == []


class TestComputeIntegration:
    def test_every_compute_attaches_contract(self):
        decomp = compute_S_final(
            raw_score=0.85,
            learned_score=0.80,
            elasticity_weight=1.0,
            decay_factor=1.0,
            trust_state="active",
        )
        assert decomp.contract_valid is True
        assert decomp.scoring_surface_version == SCORING_SURFACE_VERSION
