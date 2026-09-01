"""Explainability Dashboard v1 — contract violation as first-class telemetry.

Transforms explainability contract from validator into active observability layer.
Store: .persona_ai/explainability_telemetry.json
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from persona_ai.diagnostics.explainability_contract import (
    CONTRACT_VERSION,
    SCORING_COEFFICIENTS,
    SCORING_SURFACE_VERSION,
    ExplainabilityVerdict,
    verify_explainability_contract,
)
from persona_ai.diagnostics.fast_path_controller import (
    ScoreDecomposition,
    evaluate_runtime_score,
)
from persona_ai.diagnostics.fingerprint_learning import FingerprintPatchLearner
from persona_ai.diagnostics.promotion_gate import PromotedLearningStore, get_promoted_store

DASHBOARD_VERSION = "v1"
DEFAULT_TELEMETRY_PATH = Path(".persona_ai/explainability_telemetry.json")


@dataclass
class ContractTelemetryRecord:
    fp_id: str
    patch_id: str
    s_final: float
    contract_valid: bool
    reconstruction_delta: float
    scoring_surface_version: str
    trust_state: str
    violation_codes: list[str]
    fast_path_eligible: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContractRunSnapshot:
    run_id: str
    timestamp: str
    script_name: str
    source: str
    records: list[ContractTelemetryRecord]
    contract_pass_rate: float = 1.0
    violation_count: int = 0
    max_reconstruction_delta: float = 0.0
    scoring_surface_version: str = SCORING_SURFACE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "records": [r.to_dict() for r in self.records],
        }


@dataclass
class ExplainabilityDashboardReport:
    snapshots: list[ContractRunSnapshot]
    total_evaluations: int
    contract_pass_rate: float
    violation_rate: float
    violations_by_code: dict[str, int]
    fingerprint_violations: dict[str, int]
    reconstruction_timeline: list[dict[str, Any]]
    coefficient_versions: dict[str, str]
    active_violations: list[ContractTelemetryRecord]
    debug_trace: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dashboard_version": DASHBOARD_VERSION,
            "contract_version": CONTRACT_VERSION,
            "total_evaluations": self.total_evaluations,
            "contract_pass_rate": self.contract_pass_rate,
            "violation_rate": self.violation_rate,
            "violations_by_code": self.violations_by_code,
            "fingerprint_violations": self.fingerprint_violations,
            "reconstruction_timeline": self.reconstruction_timeline,
            "coefficient_versions": self.coefficient_versions,
            "active_violations": [r.to_dict() for r in self.active_violations],
            "snapshots": [s.to_dict() for s in self.snapshots[-20:]],
        }


class ExplainabilityTelemetryStore:
    """Append-only contract telemetry — first-class signal, not log noise."""

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_TELEMETRY_PATH
        self.snapshots: list[ContractRunSnapshot] = []
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        for snap in raw.get("snapshots", []):
            records = [ContractTelemetryRecord(**r) for r in snap.get("records", [])]
            self.snapshots.append(
                ContractRunSnapshot(
                    run_id=snap["run_id"],
                    timestamp=snap["timestamp"],
                    script_name=snap.get("script_name", ""),
                    source=snap.get("source", "runtime"),
                    records=records,
                    contract_pass_rate=snap.get("contract_pass_rate", 1.0),
                    violation_count=snap.get("violation_count", 0),
                    max_reconstruction_delta=snap.get("max_reconstruction_delta", 0.0),
                    scoring_surface_version=snap.get("scoring_surface_version", SCORING_SURFACE_VERSION),
                )
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "dashboard_version": DASHBOARD_VERSION,
            "contract_version": CONTRACT_VERSION,
            "scoring_surface_version": SCORING_SURFACE_VERSION,
            "snapshots": [s.to_dict() for s in self.snapshots[-200:]],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def append_snapshot(self, snapshot: ContractRunSnapshot) -> None:
        self.snapshots.append(snapshot)
        self.save()


def record_from_decomposition(
    decomp: ScoreDecomposition,
    *,
    fp_id: str,
    patch_id: str,
    verdict: ExplainabilityVerdict | None = None,
) -> ContractTelemetryRecord:
    verdict = verdict or verify_explainability_contract(decomp)
    return ContractTelemetryRecord(
        fp_id=fp_id,
        patch_id=patch_id,
        s_final=decomp.s_final,
        contract_valid=verdict.valid,
        reconstruction_delta=verdict.reconstruction_delta or decomp.reconstruction_delta,
        scoring_surface_version=decomp.scoring_surface_version,
        trust_state=decomp.trust_state,
        violation_codes=[v.code for v in verdict.violations],
        fast_path_eligible=decomp.fast_path_eligible,
    )


def build_run_snapshot(
    records: list[ContractTelemetryRecord],
    *,
    script_name: str = "",
    source: str = "runtime",
    run_id: str | None = None,
) -> ContractRunSnapshot:
    if not records:
        return ContractRunSnapshot(
            run_id=run_id or str(uuid.uuid4())[:8],
            timestamp=datetime.now(timezone.utc).isoformat(),
            script_name=script_name,
            source=source,
            records=[],
        )
    valid = sum(1 for r in records if r.contract_valid)
    deltas = [r.reconstruction_delta for r in records]
    return ContractRunSnapshot(
        run_id=run_id or str(uuid.uuid4())[:8],
        timestamp=datetime.now(timezone.utc).isoformat(),
        script_name=script_name,
        source=source,
        records=records,
        contract_pass_rate=round(valid / len(records), 3),
        violation_count=len(records) - valid,
        max_reconstruction_delta=round(max(deltas), 6),
    )


def persist_run_records(
    records: list[ContractTelemetryRecord],
    *,
    script_name: str = "",
    source: str = "runtime",
    store: ExplainabilityTelemetryStore | None = None,
) -> ContractRunSnapshot:
    snapshot = build_run_snapshot(records, script_name=script_name, source=source)
    if records:
        (store or ExplainabilityTelemetryStore()).append_snapshot(snapshot)
    return snapshot


class ExplainabilityDashboard:
    """Contract visibility — violations as telemetry, not post-hoc logs."""

    def __init__(
        self,
        telemetry: ExplainabilityTelemetryStore | None = None,
        *,
        promoted_store: PromotedLearningStore | None = None,
        fp_learner: FingerprintPatchLearner | None = None,
    ):
        self.telemetry = telemetry or ExplainabilityTelemetryStore()
        self.promoted_store = promoted_store or get_promoted_store()
        self.fp_learner = fp_learner or FingerprintPatchLearner()

    def live_scan(self) -> list[ContractTelemetryRecord]:
        """Evaluate contract for all promoted entries (current surface state)."""
        records: list[ContractTelemetryRecord] = []
        for entry in self.promoted_store.promoted_entries():
            fp_preds = self.fp_learner.predict_best(entry.fp_id, [entry.patch_id])
            if not fp_preds:
                continue
            pred = fp_preds[0]
            decomp = evaluate_runtime_score(
                pred,
                learned_score=pred.decayed_score,
                fp_id=entry.fp_id,
                patch_id=entry.patch_id,
                store=self.promoted_store,
            )
            records.append(record_from_decomposition(decomp, fp_id=entry.fp_id, patch_id=entry.patch_id))
        return records

    def build_report(self, *, include_live: bool = True, limit: int = 20) -> ExplainabilityDashboardReport:
        snapshots = self.telemetry.snapshots[-limit:]
        if include_live:
            live_records = self.live_scan()
            if live_records:
                snapshots = snapshots + [build_run_snapshot(live_records, source="live_scan")]

        all_records: list[ContractTelemetryRecord] = []
        for snap in snapshots:
            all_records.extend(snap.records)

        violation_codes: Counter[str] = Counter()
        fp_violations: Counter[str] = Counter()
        active_violations: list[ContractTelemetryRecord] = []

        for rec in all_records:
            if not rec.contract_valid:
                active_violations.append(rec)
                fp_violations[rec.fp_id] += 1
                for code in rec.violation_codes:
                    violation_codes[code] += 1

        total = len(all_records)
        valid = sum(1 for r in all_records if r.contract_valid)
        pass_rate = round(valid / total, 3) if total else 1.0

        timeline: list[dict[str, Any]] = []
        for snap in snapshots:
            if not snap.records:
                continue
            timeline.append(
                {
                    "run_id": snap.run_id,
                    "timestamp": snap.timestamp[:19] if snap.timestamp else "",
                    "source": snap.source,
                    "contract_pass_rate": snap.contract_pass_rate,
                    "max_reconstruction_delta": snap.max_reconstruction_delta,
                    "violation_count": snap.violation_count,
                    "evaluations": len(snap.records),
                }
            )

        coeff_versions = {
            "scoring_surface": SCORING_SURFACE_VERSION,
            "contract": CONTRACT_VERSION,
            "dashboard": DASHBOARD_VERSION,
            "registered_surfaces": ", ".join(sorted(SCORING_COEFFICIENTS)),
        }

        report = ExplainabilityDashboardReport(
            snapshots=snapshots,
            total_evaluations=total,
            contract_pass_rate=pass_rate,
            violation_rate=round(1.0 - pass_rate, 3) if total else 0.0,
            violations_by_code=dict(violation_codes),
            fingerprint_violations=dict(fp_violations),
            reconstruction_timeline=timeline,
            coefficient_versions=coeff_versions,
            active_violations=active_violations[-20:],
        )
        report.debug_trace = format_explainability_dashboard(report)
        return report


def format_explainability_dashboard(report: ExplainabilityDashboardReport) -> str:
    lines = [
        "=== Explainability Dashboard | contract telemetry (v1) ===",
        f"  evaluations: {report.total_evaluations} | pass_rate: {report.contract_pass_rate:.0%} | "
        f"violation_rate: {report.violation_rate:.0%}",
        f"  surface: {report.coefficient_versions.get('scoring_surface')} | "
        f"contract: {report.coefficient_versions.get('contract')}",
        "",
        "=== Panel A | Contract Health ===",
    ]

    if report.total_evaluations == 0:
        lines.append("  No contract telemetry yet — run smoke with learning layer active.")
        lines.append("  Records append automatically during build_learning_report().")
    else:
        status = "HEALTHY" if report.violation_rate == 0 else "VIOLATIONS_DETECTED"
        lines.append(f"  status: {status}")
        if report.violations_by_code:
            lines.append("  violations_by_code:")
            for code, count in sorted(report.violations_by_code.items(), key=lambda x: -x[1]):
                lines.append(f"    {code}: {count}")

    lines.extend(["", "=== Panel B | Reconstruction Delta Timeline ==="])
    if not report.reconstruction_timeline:
        lines.append("  (no timeline yet)")
    else:
        for point in report.reconstruction_timeline[-10:]:
            flag = " OK" if point["violation_count"] == 0 else f" FAIL({point['violation_count']})"
            lines.append(
                f"  {point['timestamp']} | {point['source'][:12]:12s} | "
                f"pass={point['contract_pass_rate']:.0%} max_delta={point['max_reconstruction_delta']:.6f} "
                f"n={point['evaluations']}{flag}"
            )

    lines.extend(["", "=== Panel C | Fingerprint Violation Tracker ==="])
    if not report.fingerprint_violations:
        lines.append("  (no fingerprint violations)")
    else:
        for fp_id, count in sorted(report.fingerprint_violations.items(), key=lambda x: -x[1])[:8]:
            lines.append(f"  {fp_id}: {count} violation(s)")

    lines.extend(["", "=== Panel D | Coefficient Registry (frozen) ==="])
    for key, val in sorted(SCORING_COEFFICIENTS.items()):
        lines.append(f"  {key}: registered")

    if report.active_violations:
        lines.extend(["", "=== Panel E | Active Violations (recent) ==="])
        for rec in report.active_violations[-5:]:
            codes = ",".join(rec.violation_codes) or "UNKNOWN"
            lines.append(
                f"  {rec.fp_id} -> {rec.patch_id} delta={rec.reconstruction_delta:.6f} [{codes}]"
            )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Explainability dashboard — contract telemetry")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-live", action="store_true", help="Skip live promoted-set scan")
    parser.add_argument("--telemetry", type=Path, default=DEFAULT_TELEMETRY_PATH)
    args = parser.parse_args(argv)

    dashboard = ExplainabilityDashboard(ExplainabilityTelemetryStore(args.telemetry))
    report = dashboard.build_report(include_live=not args.no_live)

    if args.json:
        payload = report.to_dict()
        payload["trace"] = report.debug_trace
        print(json.dumps(payload, indent=2))
    else:
        print(report.debug_trace)

    return 1 if report.violation_rate > 0 and report.total_evaluations > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
