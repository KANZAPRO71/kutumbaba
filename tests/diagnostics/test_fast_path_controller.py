"""Fast-path controller v1 tests — unified S_final scoring surface."""

from persona_ai.diagnostics.fast_path_controller import (
    DEFAULT_THRESHOLD,
    compute_S_final,
    trust_state_bias,
)


class TestComputeSFinal:
    def test_active_promoted_high_score(self):
        decomp = compute_S_final(
            raw_score=0.85,
            learned_score=0.80,
            elasticity_weight=1.0,
            decay_factor=1.0,
            trust_state="active",
            effective_attempts=3.0,
        )
        assert decomp.s_final >= DEFAULT_THRESHOLD
        assert decomp.fast_path_eligible

    def test_demoted_zero(self):
        decomp = compute_S_final(
            raw_score=0.9,
            learned_score=0.9,
            elasticity_weight=1.0,
            decay_factor=1.0,
            trust_state="demoted",
            effective_attempts=5.0,
        )
        assert decomp.s_final == 0.0
        assert not decomp.fast_path_eligible

    def test_unpromoted_bias_blocks(self):
        decomp = compute_S_final(
            raw_score=0.82,
            learned_score=0.75,
            elasticity_weight=1.0,
            decay_factor=1.0,
            trust_state="unpromoted",
            effective_attempts=3.0,
        )
        assert decomp.trust_state_bias == trust_state_bias("unpromoted")
        assert not decomp.fast_path_eligible

    def test_quarantined_not_fast_path(self):
        decomp = compute_S_final(
            raw_score=0.85,
            learned_score=0.80,
            elasticity_weight=1.0,
            decay_factor=1.0,
            trust_state="quarantined",
            effective_attempts=3.0,
        )
        assert decomp.trust_state_bias == -0.3
        assert not decomp.fast_path_eligible

    def test_elasticity_and_decay_modulation(self):
        decomp = compute_S_final(
            raw_score=0.90,
            learned_score=0.70,
            elasticity_weight=0.5,
            decay_factor=0.8,
            trust_state="active",
            effective_attempts=3.0,
        )
        expected_pre = 0.90 * 0.5 + 0.5 * 0.70
        assert decomp.pre_decay == round(expected_pre, 4)
        assert decomp.post_decay == round(expected_pre * 0.8, 4)
        assert decomp.s_final == round(decomp.post_decay, 4)

    def test_decomposition_why_score(self):
        decomp = compute_S_final(
            raw_score=0.82,
            learned_score=0.75,
            elasticity_weight=0.9,
            decay_factor=1.0,
            trust_state="active",
            effective_attempts=3.0,
            legacy_effective_score=0.738,
        )
        why = decomp.why_score()
        assert "s_final" in why
        assert "trust_bias" in why
        assert decomp.shadow_delta is not None

    def test_insufficient_attempts(self):
        decomp = compute_S_final(
            raw_score=0.95,
            learned_score=0.90,
            elasticity_weight=1.0,
            decay_factor=1.0,
            trust_state="active",
            effective_attempts=1.0,
        )
        assert decomp.s_final >= DEFAULT_THRESHOLD
        assert not decomp.fast_path_eligible
