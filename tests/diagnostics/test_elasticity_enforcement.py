"""Elasticity enforcement v1 tests."""

from datetime import datetime, timezone

from persona_ai.diagnostics.elasticity_enforcement import (
    ELASTICITY_MIN,
    ElasticityContext,
    apply_elasticity,
    compute_elasticity_weight,
    fast_path_with_elasticity,
)
from persona_ai.diagnostics.promotion_gate import (
    PromotedLearning,
    PromotedLearningStore,
    evaluate_comparison,
)
from persona_ai.diagnostics.shadow_comparator import (
    DomainMetrics,
    FingerprintShadowComparison,
    ShadowDelta,
)


def _validated_row(fp_id: str = "fp_el") -> FingerprintShadowComparison:
    return FingerprintShadowComparison(
        fp_id=fp_id,
        semantic_key="FP::EL",
        simulation=DomainMetrics(
            success_rate=0.9,
            attempts=5,
            decayed_score=0.88,
            primary_patch="raise_intent_need",
        ),
        production=DomainMetrics(success_rate=0.85, occurrences=5),
        delta=ShadowDelta(success_gap=0.05, confidence_gap=0.1, score_gap=0.03),
        classification="validated",
        stability=0.92,
    )


class TestElasticityFunction:
    def test_demoted_zero(self):
        ctx = ElasticityContext("fp_x", "p1", lifecycle_status="demoted", drift_severity=0.9)
        weight, _ = compute_elasticity_weight(ctx)
        assert weight == 0.0
        result = apply_elasticity(0.82, ctx)
        assert result.effective_score == 0.0

    def test_risk_attenuation_formula(self):
        ctx = ElasticityContext(
            "fp_x",
            "p1",
            lifecycle_status="active",
            drift_severity=0.5,
            prod_trend_delta=-0.2,
        )
        weight, components = compute_elasticity_weight(ctx)
        expected = 1.0 - 0.5 * 0.6 - 0.2 * 0.4
        assert weight == round(max(ELASTICITY_MIN, expected), 3)
        assert components["drift_penalty"] == 0.3
        assert components["trend_penalty"] == 0.08

    def test_recovery_boost(self):
        ctx = ElasticityContext(
            "fp_x",
            "p1",
            lifecycle_status="active",
            drift_severity=0.1,
            trust_decision="RECOVERY_STABLE",
        )
        weight, _ = compute_elasticity_weight(ctx)
        assert weight == 1.0

    def test_false_promotion_penalty(self):
        ctx = ElasticityContext(
            "fp_x",
            "p1",
            lifecycle_status="active",
            false_promotion_flagged=True,
        )
        weight, components = compute_elasticity_weight(ctx)
        assert weight == round(1.0 * 0.7, 3)
        assert components["false_promotion_factor"] == 0.7

    def test_effective_score_drops_below_threshold(self):
        ctx = ElasticityContext(
            "fp_x",
            "p1",
            lifecycle_status="active",
            drift_severity=0.8,
            prod_trend_delta=-0.3,
        )
        result = apply_elasticity(0.82, ctx)
        assert result.elasticity_weight == 0.4
        assert result.effective_score == round(0.82 * 0.4, 3)
        assert result.effective_score < 0.7


class TestFastPathIntegration:
    def test_elasticity_blocks_fast_path(self):
        ctx = ElasticityContext(
            "fp_x",
            "p1",
            lifecycle_status="active",
            drift_severity=0.9,
            prod_trend_delta=-0.4,
        )
        result = apply_elasticity(0.82, ctx)
        assert result.effective_score < 0.7
        eligible = (
            3.0 >= 2.0
            and result.raw_score >= 0.7 * 0.85
            and result.effective_score >= 0.7
        )
        assert not eligible

    def test_resolve_from_promoted_store(self, tmp_path):
        store_path = tmp_path / "promoted.json"
        store = PromotedLearningStore(store_path)
        store.apply_decisions([evaluate_comparison(_validated_row("fp_store"))])
        store.save()

        eligible, result = fast_path_with_elasticity(
            raw_score=0.85,
            effective_attempts=3.0,
            fp_id="fp_store",
            patch_id="raise_intent_need",
            score_threshold=0.7,
            min_effective_attempts=2.0,
            promoted_ok=True,
            store=PromotedLearningStore(store_path),
        )
        assert result.elasticity_weight == 1.0
        assert eligible
