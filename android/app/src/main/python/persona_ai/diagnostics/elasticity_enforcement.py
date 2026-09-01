"""Elasticity Enforcement v1 — continuous trust attenuation for runtime modulation.

Maps trust stack signals to elasticity_weight ∈ [0.2, 1.0] (0.0 if demoted).
Applied after promotion/survival gates; modulates suggestion strength only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from persona_ai.diagnostics.promotion_gate import (
    DEFAULT_STORE_PATH,
    PromotedLearning,
    PromotedLearningStore,
    get_promoted_store,
)
from persona_ai.diagnostics.shadow_drift_alerts import (
    DEFAULT_ALERTS_PATH,
    evaluate_drift,
)

ELASTICITY_VERSION = "v1"
ELASTICITY_MIN = 0.2
ELASTICITY_MAX = 1.0
FALSE_PROMOTION_PENALTY = 0.7
RECOVERY_BOOST = 0.1

DEFAULT_DECISIONS_PATH = Path(".persona_ai/trust_decisions.json")


@dataclass
class ElasticityContext:
    fp_id: str
    patch_id: str
    lifecycle_status: str = "none"
    drift_severity: float = 0.0
    prod_trend_delta: float = 0.0
    stability_derivative: float = 0.0
    trust_decision: str | None = None
    false_promotion_flagged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ElasticityResult:
    raw_score: float
    elasticity_weight: float
    effective_score: float
    context: ElasticityContext
    components: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_score": self.raw_score,
            "elasticity_weight": self.elasticity_weight,
            "effective_score": self.effective_score,
            "context": self.context.to_dict(),
            "components": self.components,
        }


def _load_latest_drift_metrics(
    fp_id: str,
    patch_id: str,
    alerts_path: Path | None = None,
) -> tuple[float, float, float]:
    path = alerts_path or DEFAULT_ALERTS_PATH
    if not path.exists():
        return 0.0, 0.0, 0.0
    raw = json.loads(path.read_text(encoding="utf-8"))
    snapshots = raw.get("snapshots", [])
    for snap in reversed(snapshots):
        for alert in snap.get("alerts", []):
            if alert.get("fp_id") == fp_id and alert.get("patch_id") == patch_id:
                sig = alert.get("signals", {})
                return (
                    float(alert.get("severity", 0.0)),
                    float(sig.get("prod_trend_delta", 0.0)),
                    float(sig.get("stability_derivative", 0.0)),
                )
    return 0.0, 0.0, 0.0


def _load_latest_trust_decision(
    fp_id: str,
    patch_id: str,
    decisions_path: Path | None = None,
) -> str | None:
    path = decisions_path or DEFAULT_DECISIONS_PATH
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    for batch in reversed(raw.get("history", [])):
        for row in batch.get("decisions", []):
            if row.get("fp_id") == fp_id and row.get("patch_id") == patch_id:
                return row.get("recommendation")
    return None


def _false_promotion_flagged(
    entry: PromotedLearning | None,
    fp_id: str,
    patch_id: str,
) -> bool:
    if entry is None:
        return False
    if entry.status in ("quarantined", "demoted"):
        return True
    if entry.false_promotion_class:
        return True
    audit_path = Path(".persona_ai/false_promotion_audit.json")
    if not audit_path.exists():
        return False
    raw = json.loads(audit_path.read_text(encoding="utf-8"))
    for ev in reversed(raw.get("events", [])[-50:]):
        if ev.get("fp_id") == fp_id and ev.get("patch_id") == patch_id:
            if ev.get("status") in ("quarantined", "demoted"):
                return True
    return False


def build_elasticity_context(
    fp_id: str,
    patch_id: str,
    *,
    store: PromotedLearningStore | None = None,
    live_drift: bool = False,
    comparator=None,
) -> ElasticityContext:
    """Assemble elasticity inputs from promoted store + drift/decision artifacts."""
    store = store or get_promoted_store()
    entry = store.get(fp_id, patch_id)
    status = entry.status if entry else "none"

    severity, prod_trend, stability_deriv = _load_latest_drift_metrics(fp_id, patch_id)

    if live_drift and entry is not None and comparator is not None:
        from persona_ai.diagnostics.shadow_comparator import load_production_entries

        shadow = comparator.build_report()
        shadow_by_fp = {row.fp_id: row for row in shadow.comparisons}
        prod_entries = load_production_entries(comparator.ingest_path)
        alert = evaluate_drift(
            entry,
            shadow_row=shadow_by_fp.get(fp_id),
            prod_entries=prod_entries,
        )
        severity = alert.severity
        prod_trend = alert.signals.prod_trend_delta
        stability_deriv = alert.signals.stability_derivative

    trust_decision = _load_latest_trust_decision(fp_id, patch_id)
    fp_flagged = _false_promotion_flagged(entry, fp_id, patch_id)

    return ElasticityContext(
        fp_id=fp_id,
        patch_id=patch_id,
        lifecycle_status=status,
        drift_severity=severity,
        prod_trend_delta=prod_trend,
        stability_derivative=stability_deriv,
        trust_decision=trust_decision,
        false_promotion_flagged=fp_flagged,
    )


def compute_elasticity_weight(ctx: ElasticityContext) -> tuple[float, dict[str, float]]:
    """Formal v1 attenuation function E = f(drift, trend, state, false promotion)."""
    components: dict[str, float] = {
        "base": 1.0,
        "drift_penalty": 0.0,
        "trend_penalty": 0.0,
        "recovery_boost": 0.0,
        "false_promotion_factor": 1.0,
        "lifecycle_cap": ELASTICITY_MAX,
    }

    if ctx.lifecycle_status == "demoted":
        return 0.0, {**components, "lifecycle_cap": 0.0}

    weight = 1.0
    drift_penalty = ctx.drift_severity * 0.6
    trend_penalty = max(0.0, -ctx.prod_trend_delta) * 0.4
    weight -= drift_penalty
    weight -= trend_penalty
    components["drift_penalty"] = round(drift_penalty, 3)
    components["trend_penalty"] = round(trend_penalty, 3)

    if ctx.trust_decision == "RECOVERY_STABLE":
        weight += RECOVERY_BOOST
        components["recovery_boost"] = RECOVERY_BOOST

    if ctx.false_promotion_flagged:
        weight *= FALSE_PROMOTION_PENALTY
        components["false_promotion_factor"] = FALSE_PROMOTION_PENALTY

    if ctx.lifecycle_status == "quarantined":
        weight = min(weight, ELASTICITY_MIN)
        components["lifecycle_cap"] = ELASTICITY_MIN
    elif ctx.lifecycle_status == "degraded":
        weight = min(weight, 0.4)
        components["lifecycle_cap"] = 0.4

    if ctx.lifecycle_status != "demoted":
        weight = max(ELASTICITY_MIN, min(ELASTICITY_MAX, weight))

    return round(weight, 3), components


def apply_elasticity(raw_score: float, ctx: ElasticityContext) -> ElasticityResult:
    weight, components = compute_elasticity_weight(ctx)
    if ctx.lifecycle_status == "demoted":
        effective = 0.0
    else:
        effective = round(raw_score * weight, 3)
    return ElasticityResult(
        raw_score=raw_score,
        elasticity_weight=weight,
        effective_score=effective,
        context=ctx,
        components=components,
    )


def resolve_elasticity(
    fp_id: str,
    patch_id: str,
    raw_score: float,
    *,
    store: PromotedLearningStore | None = None,
) -> ElasticityResult:
    ctx = build_elasticity_context(fp_id, patch_id, store=store)
    return apply_elasticity(raw_score, ctx)


def fast_path_with_elasticity(
    *,
    raw_score: float,
    effective_attempts: float,
    fp_id: str,
    patch_id: str,
    score_threshold: float,
    min_effective_attempts: float,
    promoted_ok: bool,
    store: PromotedLearningStore | None = None,
) -> tuple[bool, ElasticityResult]:
    """Fast-path eligibility using effective_score = raw_score * elasticity_weight."""
    result = resolve_elasticity(fp_id, patch_id, raw_score, store=store)
    learner_ok = (
        effective_attempts >= min_effective_attempts
        and result.raw_score >= score_threshold * 0.85
    )
    effective_ok = result.effective_score >= score_threshold
    eligible = learner_ok and promoted_ok and effective_ok
    return eligible, result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Elasticity enforcement — trust attenuation preview")
    parser.add_argument("--fp-id", required=True)
    parser.add_argument("--patch-id", required=True)
    parser.add_argument("--raw-score", type=float, default=0.82)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    store = PromotedLearningStore(args.store)
    result = resolve_elasticity(args.fp_id, args.patch_id, args.raw_score, store=store)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(
            f"elasticity [{args.fp_id}] -> {args.patch_id}\n"
            f"  raw={result.raw_score:.2f} weight={result.elasticity_weight:.2f} "
            f"effective={result.effective_score:.2f}\n"
            f"  status={result.context.lifecycle_status} "
            f"drift={result.context.drift_severity:.2f} "
            f"trend={result.context.prod_trend_delta:+.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
