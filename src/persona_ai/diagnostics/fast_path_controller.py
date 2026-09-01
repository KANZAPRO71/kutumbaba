"""Fast-path Controller v1 — unified runtime scoring surface (S_final).

Collapses promotion, elasticity, decay, and trust state into one scalar field
with full decomposition trace for debuggability.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from persona_ai.diagnostics.elasticity_enforcement import resolve_elasticity
from persona_ai.diagnostics.fingerprint_learning import FingerprintPatchPrediction
from persona_ai.diagnostics.promotion_gate import PromotedLearningStore, get_promoted_store

CONTROLLER_VERSION = "v1"
SCORING_SURFACE_VERSION = "S_final_v1"
DEFAULT_THRESHOLD = 0.7
MIN_EFFECTIVE_ATTEMPTS = 2.0
LEARNED_BLEND = 0.5

TRUST_STATE_BIAS: dict[str, float] = {
    "active": 0.0,
    "degraded": -0.1,
    "quarantined": -0.3,
    "unpromoted": -0.45,
    "none": -0.45,
}


@dataclass
class RuntimeScoreInputs:
    raw_score: float
    learned_score: float
    elasticity_weight: float
    decay_factor: float
    trust_state: str
    effective_attempts: float = 0.0
    threshold: float = DEFAULT_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreDecomposition:
    raw_score: float
    learned_score: float
    elasticity_weight: float
    decay_factor: float
    trust_state: str
    trust_state_bias: float
    raw_elastic_component: float
    learned_component: float
    pre_decay: float
    post_decay: float
    s_final: float
    threshold: float
    fast_path_eligible: bool
    effective_attempts: float
    legacy_effective_score: float | None = None
    shadow_delta: float | None = None
    scoring_surface_version: str = SCORING_SURFACE_VERSION
    contract_valid: bool = True
    reconstruction_delta: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def why_score(self) -> dict[str, float]:
        return {
            "raw_elastic_contribution": self.raw_elastic_component,
            "learned_contribution": self.learned_component,
            "elasticity_effect": self.elasticity_weight,
            "decay_effect": self.decay_factor,
            "trust_bias": self.trust_state_bias,
            "s_final": self.s_final,
        }


def trust_state_bias(trust_state: str) -> float:
    if trust_state == "demoted":
        return 0.0
    return TRUST_STATE_BIAS.get(trust_state, TRUST_STATE_BIAS["unpromoted"])


def compute_S_final(
    *,
    raw_score: float,
    learned_score: float,
    elasticity_weight: float,
    decay_factor: float,
    trust_state: str,
    effective_attempts: float = MIN_EFFECTIVE_ATTEMPTS,
    threshold: float = DEFAULT_THRESHOLD,
    legacy_effective_score: float | None = None,
) -> ScoreDecomposition:
    """Unified runtime score: single scalar field with decomposition."""
    if trust_state == "demoted":
        decomp = ScoreDecomposition(
            raw_score=raw_score,
            learned_score=learned_score,
            elasticity_weight=elasticity_weight,
            decay_factor=decay_factor,
            trust_state=trust_state,
            trust_state_bias=0.0,
            raw_elastic_component=0.0,
            learned_component=0.0,
            pre_decay=0.0,
            post_decay=0.0,
            s_final=0.0,
            threshold=threshold,
            fast_path_eligible=False,
            effective_attempts=effective_attempts,
            legacy_effective_score=legacy_effective_score,
            shadow_delta=(0.0 - legacy_effective_score) if legacy_effective_score is not None else None,
        )
        return _finalize_decomp(decomp)

    bias = trust_state_bias(trust_state)
    raw_elastic = round(raw_score * elasticity_weight, 4)
    learned_component = round(LEARNED_BLEND * learned_score, 4)
    pre_decay = round(raw_elastic + learned_component, 4)
    post_decay = round(pre_decay * decay_factor, 4)
    s_final = round(max(0.0, min(1.0, post_decay + bias)), 4)

    attempts_ok = effective_attempts >= MIN_EFFECTIVE_ATTEMPTS
    eligible = attempts_ok and s_final >= threshold and trust_state == "active"

    shadow_delta = None
    if legacy_effective_score is not None:
        shadow_delta = round(s_final - legacy_effective_score, 4)

    return _finalize_decomp(ScoreDecomposition(
        raw_score=raw_score,
        learned_score=learned_score,
        elasticity_weight=elasticity_weight,
        decay_factor=decay_factor,
        trust_state=trust_state,
        trust_state_bias=bias,
        raw_elastic_component=raw_elastic,
        learned_component=learned_component,
        pre_decay=pre_decay,
        post_decay=post_decay,
        s_final=s_final,
        threshold=threshold,
        fast_path_eligible=eligible,
        effective_attempts=effective_attempts,
        legacy_effective_score=legacy_effective_score,
        shadow_delta=shadow_delta,
    ))


def _finalize_decomp(decomp: ScoreDecomposition) -> ScoreDecomposition:
    from persona_ai.diagnostics.explainability_contract import verify_explainability_contract

    verdict = verify_explainability_contract(decomp)
    decomp.contract_valid = verdict.valid
    decomp.reconstruction_delta = verdict.reconstruction_delta or 0.0
    return decomp


def resolve_trust_state(
    fp_id: str,
    patch_id: str,
    *,
    store: PromotedLearningStore | None = None,
) -> str:
    store = store or get_promoted_store()
    entry = store.get(fp_id, patch_id)
    if entry is None:
        return "unpromoted"
    return entry.status


def evaluate_runtime_score(
    fp_pred: FingerprintPatchPrediction,
    *,
    learned_score: float,
    fp_id: str,
    patch_id: str,
    store: PromotedLearningStore | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    include_shadow: bool = True,
) -> ScoreDecomposition:
    """Build unified score from fingerprint prediction + trust stack signals."""
    store = store or get_promoted_store()
    trust_state = resolve_trust_state(fp_id, patch_id, store=store)
    el = resolve_elasticity(fp_id, patch_id, fp_pred.decayed_score, store=store)

    legacy_effective = None
    if include_shadow:
        legacy_effective = round(fp_pred.decayed_score * el.elasticity_weight, 4)

    return compute_S_final(
        raw_score=fp_pred.decayed_score,
        learned_score=learned_score,
        elasticity_weight=el.elasticity_weight,
        decay_factor=fp_pred.decay_factor,
        trust_state=trust_state,
        effective_attempts=fp_pred.effective_attempts,
        threshold=threshold,
        legacy_effective_score=legacy_effective,
    )


def format_score_decomposition(decomp: ScoreDecomposition) -> str:
    why = decomp.why_score()
    lines = [
        f"  S_final={decomp.s_final:.3f} (threshold={decomp.threshold:.2f}) "
        f"eligible={decomp.fast_path_eligible}",
        f"    trust_state={decomp.trust_state} bias={decomp.trust_state_bias:+.2f}",
        f"    raw*elastic={decomp.raw_elastic_component:.3f} "
        f"+ learned={decomp.learned_component:.3f} -> pre_decay={decomp.pre_decay:.3f}",
        f"    * decay={decomp.decay_factor:.3f} -> post={decomp.post_decay:.3f} + bias -> S_final",
        f"    why_score: {why}",
    ]
    if decomp.shadow_delta is not None and decomp.legacy_effective_score is not None:
        lines.append(
            f"    shadow A/B: legacy_effective={decomp.legacy_effective_score:.3f} "
            f"delta={decomp.shadow_delta:+.3f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Fast-path controller — unified S_final preview")
    parser.add_argument("--raw-score", type=float, default=0.82)
    parser.add_argument("--learned-score", type=float, default=0.75)
    parser.add_argument("--elasticity", type=float, default=1.0)
    parser.add_argument("--decay", type=float, default=1.0)
    parser.add_argument("--trust-state", default="active")
    parser.add_argument("--attempts", type=float, default=3.0)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    decomp = compute_S_final(
        raw_score=args.raw_score,
        learned_score=args.learned_score,
        elasticity_weight=args.elasticity,
        decay_factor=args.decay,
        trust_state=args.trust_state,
        effective_attempts=args.attempts,
        threshold=args.threshold,
        legacy_effective_score=round(args.raw_score * args.elasticity, 4),
    )

    if args.json:
        print(json.dumps(decomp.to_dict(), indent=2))
    else:
        print("=== Fast-path Controller | unified S_final ===")
        print(format_score_decomposition(decomp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
