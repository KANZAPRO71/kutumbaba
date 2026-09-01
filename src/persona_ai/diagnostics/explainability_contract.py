"""Explainability Contract v1 — interpretability invariants for S_final surface.

Guards against decomposition lag and shadow policy creep by enforcing:
  1. Frozen coefficient versioning (S_final_v1)
  2. Reconstruction: post_decay + trust_bias ≈ S_final (after clamp)
  3. Per-component contribution bounds
  4. Silent contributor drift detection across coefficient versions
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from persona_ai.diagnostics.fast_path_controller import (
    CONTROLLER_VERSION,
    ScoreDecomposition,
)

CONTRACT_VERSION = "v1"
RECONSTRUCTION_EPSILON = 0.001

# Frozen coefficient registry — bump SCORING_SURFACE_VERSION on any change.
SCORING_SURFACE_VERSION = "S_final_v1"

SCORING_COEFFICIENTS: dict[str, dict[str, float | dict[str, float]]] = {
    "S_final_v1": {
        "learned_blend": 0.5,
        "default_threshold": 0.7,
        "min_effective_attempts": 2.0,
        "trust_state_bias": {
            "active": 0.0,
            "degraded": -0.1,
            "quarantined": -0.3,
            "unpromoted": -0.45,
            "none": -0.45,
        },
    },
    "elasticity_v1": {
        "drift_penalty_factor": 0.6,
        "trend_penalty_factor": 0.4,
        "false_promotion_penalty": 0.7,
        "recovery_boost": 0.1,
        "elasticity_min": 0.2,
        "elasticity_max": 1.0,
    },
}

CONTRIBUTION_BOUNDS: dict[str, tuple[float, float]] = {
    "raw_elastic_component": (0.0, 1.0),
    "learned_component": (0.0, 0.5),
    "pre_decay": (0.0, 1.5),
    "post_decay": (0.0, 1.5),
    "trust_state_bias": (-0.5, 0.1),
    "s_final": (0.0, 1.0),
    "elasticity_weight": (0.0, 1.0),
    "decay_factor": (0.0, 1.0),
}


@dataclass
class ExplainabilityViolation:
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExplainabilityVerdict:
    valid: bool
    scoring_surface_version: str
    controller_version: str
    contract_version: str
    violations: list[ExplainabilityViolation]
    reconstruction_delta: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "scoring_surface_version": self.scoring_surface_version,
            "controller_version": self.controller_version,
            "contract_version": self.contract_version,
            "reconstruction_delta": self.reconstruction_delta,
            "violations": [v.to_dict() for v in self.violations],
        }


def reconstruct_s_final(decomp: ScoreDecomposition) -> float:
    """Reconstruct S_final from decomposition (pre-clamp formula)."""
    if decomp.trust_state == "demoted":
        return 0.0
    post = decomp.pre_decay * decomp.decay_factor
    unclamped = post + decomp.trust_state_bias
    return round(max(0.0, min(1.0, unclamped)), 4)


def verify_reconstruction(
    decomp: ScoreDecomposition,
    *,
    epsilon: float = RECONSTRUCTION_EPSILON,
) -> ExplainabilityViolation | None:
    reconstructed = reconstruct_s_final(decomp)
    delta = abs(reconstructed - decomp.s_final)
    if delta > epsilon:
        return ExplainabilityViolation(
            code="RECONSTRUCTION_MISMATCH",
            message="decomposition does not reconstruct S_final within epsilon",
            detail={
                "s_final": decomp.s_final,
                "reconstructed": reconstructed,
                "delta": round(delta, 6),
                "epsilon": epsilon,
            },
        )
    return None


def verify_pre_decay_components(decomp: ScoreDecomposition) -> ExplainabilityViolation | None:
    if decomp.trust_state == "demoted":
        return None
    coeffs = SCORING_COEFFICIENTS["S_final_v1"]
    learned_blend = float(coeffs["learned_blend"])
    expected_raw = round(decomp.raw_score * decomp.elasticity_weight, 4)
    expected_learned = round(learned_blend * decomp.learned_score, 4)
    expected_pre = round(expected_raw + expected_learned, 4)

    if abs(decomp.raw_elastic_component - expected_raw) > RECONSTRUCTION_EPSILON:
        return ExplainabilityViolation(
            code="RAW_ELASTIC_MISMATCH",
            message="raw_elastic_component drift from raw_score * elasticity",
            detail={"expected": expected_raw, "actual": decomp.raw_elastic_component},
        )
    if abs(decomp.learned_component - expected_learned) > RECONSTRUCTION_EPSILON:
        return ExplainabilityViolation(
            code="LEARNED_COMPONENT_MISMATCH",
            message="learned_component drift from learned_blend * learned_score",
            detail={"expected": expected_learned, "actual": decomp.learned_component},
        )
    if abs(decomp.pre_decay - expected_pre) > RECONSTRUCTION_EPSILON:
        return ExplainabilityViolation(
            code="PRE_DECAY_MISMATCH",
            message="pre_decay != raw_elastic + learned_component",
            detail={"expected": expected_pre, "actual": decomp.pre_decay},
        )
    return None


def verify_contribution_bounds(decomp: ScoreDecomposition) -> list[ExplainabilityViolation]:
    violations: list[ExplainabilityViolation] = []
    checks = {
        "raw_elastic_component": decomp.raw_elastic_component,
        "learned_component": decomp.learned_component,
        "pre_decay": decomp.pre_decay,
        "post_decay": decomp.post_decay,
        "trust_state_bias": decomp.trust_state_bias,
        "s_final": decomp.s_final,
        "elasticity_weight": decomp.elasticity_weight,
        "decay_factor": decomp.decay_factor,
    }
    for name, value in checks.items():
        lo, hi = CONTRIBUTION_BOUNDS[name]
        if not lo - RECONSTRUCTION_EPSILON <= value <= hi + RECONSTRUCTION_EPSILON:
            violations.append(
                ExplainabilityViolation(
                    code="BOUNDS_VIOLATION",
                    message=f"{name}={value} outside [{lo}, {hi}]",
                    detail={"field": name, "value": value, "bounds": [lo, hi]},
                )
            )
    return violations


def verify_trust_bias_registered(decomp: ScoreDecomposition) -> ExplainabilityViolation | None:
    if decomp.trust_state == "demoted":
        return None
    registry = SCORING_COEFFICIENTS["S_final_v1"]["trust_state_bias"]
    assert isinstance(registry, dict)
    expected = registry.get(decomp.trust_state, registry.get("unpromoted", -0.45))
    if abs(decomp.trust_state_bias - float(expected)) > RECONSTRUCTION_EPSILON:
        return ExplainabilityViolation(
            code="TRUST_BIAS_DRIFT",
            message="trust_state_bias not in frozen coefficient registry",
            detail={"trust_state": decomp.trust_state, "expected": expected, "actual": decomp.trust_state_bias},
        )
    return None


def verify_explainability_contract(
    decomp: ScoreDecomposition,
    *,
    epsilon: float = RECONSTRUCTION_EPSILON,
) -> ExplainabilityVerdict:
    """Full contract check — call after every compute_S_final in strict paths."""
    violations: list[ExplainabilityViolation] = []

    for check in (
        verify_reconstruction(decomp, epsilon=epsilon),
        verify_pre_decay_components(decomp),
        verify_trust_bias_registered(decomp),
    ):
        if check is not None:
            violations.append(check)
    violations.extend(verify_contribution_bounds(decomp))

    reconstructed = reconstruct_s_final(decomp)
    delta = abs(reconstructed - decomp.s_final)

    return ExplainabilityVerdict(
        valid=len(violations) == 0,
        scoring_surface_version=SCORING_SURFACE_VERSION,
        controller_version=CONTROLLER_VERSION,
        contract_version=CONTRACT_VERSION,
        violations=violations,
        reconstruction_delta=round(delta, 6),
    )


def assert_explainability_contract(decomp: ScoreDecomposition) -> ExplainabilityVerdict:
    verdict = verify_explainability_contract(decomp)
    if not verdict.valid:
        codes = ", ".join(v.code for v in verdict.violations)
        raise ExplainabilityContractError(
            f"Explainability contract violated: {codes}",
            verdict=verdict,
        )
    return verdict


def detect_coefficient_drift(
    old_version: str,
    new_version: str,
) -> list[ExplainabilityViolation]:
    """Detect silent policy shift between frozen coefficient versions."""
    old = SCORING_COEFFICIENTS.get(old_version, {})
    new = SCORING_COEFFICIENTS.get(new_version, {})
    violations: list[ExplainabilityViolation] = []

    all_keys = set(old) | set(new)
    for key in sorted(all_keys):
        if old.get(key) != new.get(key):
            violations.append(
                ExplainabilityViolation(
                    code="COEFFICIENT_VERSION_DRIFT",
                    message=f"coefficient '{key}' changed between {old_version} and {new_version}",
                    detail={"key": key, "old": old.get(key), "new": new.get(key)},
                )
            )
    return violations


class ExplainabilityContractError(Exception):
    def __init__(self, message: str, *, verdict: ExplainabilityVerdict):
        super().__init__(message)
        self.verdict = verdict


def format_verdict(verdict: ExplainabilityVerdict) -> str:
    lines = [
        f"=== Explainability Contract | {verdict.contract_version} ===",
        f"  surface={verdict.scoring_surface_version} controller={verdict.controller_version}",
        f"  valid={verdict.valid} reconstruction_delta={verdict.reconstruction_delta}",
    ]
    for v in verdict.violations:
        lines.append(f"  [VIOLATION:{v.code}] {v.message}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    from persona_ai.diagnostics.fast_path_controller import compute_S_final

    parser = argparse.ArgumentParser(description="Explainability contract verifier")
    parser.add_argument("--raw-score", type=float, default=0.82)
    parser.add_argument("--learned-score", type=float, default=0.75)
    parser.add_argument("--elasticity", type=float, default=1.0)
    parser.add_argument("--decay", type=float, default=1.0)
    parser.add_argument("--trust-state", default="active")
    parser.add_argument("--verify", action="store_true", help="CI: verify explainability on canonical batch")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.verify:
        from persona_ai.diagnostics.manifold_ci import build_canonical_fixture, check_explainability_contract

        result = check_explainability_contract()
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(format_verdict(verify_explainability_contract(build_canonical_fixture().decomps[0])))
            print(f"  verify: {result.status} — {result.message}")
        return result.exit_code

    decomp = compute_S_final(
        raw_score=args.raw_score,
        learned_score=args.learned_score,
        elasticity_weight=args.elasticity,
        decay_factor=args.decay,
        trust_state=args.trust_state,
    )
    verdict = verify_explainability_contract(decomp)

    if args.json:
        print(json.dumps(verdict.to_dict(), indent=2))
    else:
        print(format_verdict(verdict))
    return 0 if verdict.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
