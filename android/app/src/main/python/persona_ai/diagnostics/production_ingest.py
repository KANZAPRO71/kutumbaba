"""Production ingest v1 — read-only observer mode (shadow system, no runtime authority).

GUARDRAIL: This module MUST NOT be imported by persona_ai.behavior.*
Learning stores written here are non-authoritative observation logs only.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from persona_ai.diagnostics.failure_taxonomy import FailureReport

if TYPE_CHECKING:
    from persona_ai.sim.smoke_openai import SmokeReport

LEARNING_VERSION = "v1.2"
DEFAULT_LOG_PATH = Path(".persona_ai/production_ingest_log.json")

OutcomeLabel = Literal[
    "observed_success",
    "observed_failure",
    "degraded",
    "partial_success",
    "observed",
]


@dataclass
class FingerprintObservation:
    fp_id: str
    patch_suggestion: str | None
    decayed_score: float | None
    raw_score: float | None
    context: str
    outcome: OutcomeLabel
    turn_index: int | None = None
    semantic_key: str = ""


@dataclass
class ProductionIngestEntry:
    session_id: str
    timestamp: str
    source: str
    context: str
    fingerprints: list[FingerprintObservation]
    system_snapshot: dict[str, Any]
    contract_pass_rate: float = 0.0
    readiness_score: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["fingerprints"] = [asdict(f) for f in self.fingerprints]
        return row


def affects_runtime_decision() -> bool:
    """Production ingest never influences runtime behavior."""
    return False


def classify_turn_outcome(
    turn_index: int | None,
    *,
    contracts_passed: dict[int, bool],
    cps_score: float,
    had_failure: bool,
) -> OutcomeLabel:
    if turn_index is None:
        return "partial_success" if not had_failure else "observed_failure"
    if turn_index in contracts_passed:
        return "observed_success" if contracts_passed[turn_index] else "observed_failure"
    if cps_score > 0:
        return "degraded"
    if not had_failure:
        return "partial_success"
    return "observed"


def build_observations(report: SmokeReport) -> list[FingerprintObservation]:
    failure: FailureReport | None = report.failure
    if not failure or not failure.fingerprints or not failure.fingerprints.items:
        return []

    contracts = {c.turn_index: c.passed for c in report.smoke.behavior_contracts}
    learning = failure.intervention_learning
    patch_by_fp: dict[str, tuple[str, float | None, float | None]] = {}
    if learning:
        for rec in learning.fingerprint_recommendations:
            patch_by_fp[rec.fingerprint_id] = (rec.patch_id, rec.score, None)
        for pred in learning.predictions:
            if pred.fingerprint_id and pred.fingerprint_id not in patch_by_fp:
                patch_by_fp[pred.fingerprint_id] = (
                    pred.patch_id,
                    pred.fp_score or pred.blended_score,
                    pred.success_rate,
                )

    failure_turns = {
        e.turn_index for e in failure.events if e.turn_index is not None
    }

    observations: list[FingerprintObservation] = []
    for item in failure.fingerprints.items:
        fp = item.fingerprint
        turn_idx = item.turn_index
        cps = 0.0
        if turn_idx is not None and turn_idx < len(report.session.turns):
            cps = report.session.turns[turn_idx].cps_score

        patch_info = patch_by_fp.get(fp.fingerprint_id, (None, None, None))
        outcome = classify_turn_outcome(
            turn_idx,
            contracts_passed=contracts,
            cps_score=cps,
            had_failure=turn_idx in failure_turns if turn_idx is not None else bool(failure.events),
        )

        observations.append(
            FingerprintObservation(
                fp_id=fp.fingerprint_id,
                patch_suggestion=patch_info[0],
                decayed_score=patch_info[1],
                raw_score=patch_info[2],
                context=report.script_name,
                outcome=outcome,
                turn_index=turn_idx,
                semantic_key=fp.semantic_key,
            )
        )
    return observations


def build_ingest_entry(
    report: SmokeReport,
    *,
    session_id: str,
    source: str = "smoke",
) -> ProductionIngestEntry:
    failure = report.failure
    learning = failure.intervention_learning if failure else None
    return ProductionIngestEntry(
        session_id=session_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        source=source,
        context=report.script_name,
        fingerprints=build_observations(report),
        system_snapshot={
            "fast_path_used": bool(learning and learning.fast_path_eligible),
            "fast_path_would_suggest": learning.recommended_patch if learning else None,
            "learning_version": LEARNING_VERSION,
            "affects_runtime": affects_runtime_decision(),
            "adapter": report.adapter,
            "grade": report.smoke.grade,
        },
        contract_pass_rate=report.smoke.contract_pass_rate,
        readiness_score=failure.readiness_score if failure else 100.0,
    )


class ProductionIngestor:
    """Buffered write-only production observer — never updates learning authority stores."""

    DEFAULT_BUFFER_SIZE = 10
    DEFAULT_FLUSH_INTERVAL_S = 30.0

    def __init__(
        self,
        log_path: Path | None = None,
        *,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        flush_interval_s: float = DEFAULT_FLUSH_INTERVAL_S,
    ):
        self.log_path = log_path or DEFAULT_LOG_PATH
        self.buffer_size = buffer_size
        self.flush_interval_s = flush_interval_s
        self._buffer: list[dict[str, Any]] = []
        self._last_flush_monotonic = time.monotonic()
        self._total_observed = 0

    def observe(
        self,
        report: SmokeReport,
        *,
        session_id: str,
        source: str = "smoke",
        force_flush: bool = False,
    ) -> ProductionIngestEntry:
        assert not affects_runtime_decision(), "production ingest must remain read-only"
        entry = build_ingest_entry(report, session_id=session_id, source=source)
        self._buffer.append(entry.to_dict())
        self._total_observed += 1
        if force_flush or self._should_flush():
            self.flush()
        return entry

    def _should_flush(self) -> bool:
        if len(self._buffer) >= self.buffer_size:
            return True
        return (time.monotonic() - self._last_flush_monotonic) >= self.flush_interval_s

    def flush(self) -> int:
        if not self._buffer:
            return 0
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict[str, Any]] = []
        if self.log_path.exists():
            raw = json.loads(self.log_path.read_text(encoding="utf-8"))
            existing = list(raw.get("entries", []))
        existing.extend(self._buffer)
        payload = {
            "version": 1,
            "learning_version": LEARNING_VERSION,
            "entries": existing,
        }
        self.log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        flushed = len(self._buffer)
        self._buffer.clear()
        self._last_flush_monotonic = time.monotonic()
        return flushed

    @property
    def pending_count(self) -> int:
        return len(self._buffer)

    @property
    def total_observed(self) -> int:
        return self._total_observed

    def load_entries(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        raw = json.loads(self.log_path.read_text(encoding="utf-8"))
        return list(raw.get("entries", []))


_default_ingestor: ProductionIngestor | None = None


def get_ingestor(log_path: Path | None = None) -> ProductionIngestor:
    global _default_ingestor
    if _default_ingestor is None:
        _default_ingestor = ProductionIngestor(log_path)
    return _default_ingestor


def production_coverage(entries: list[dict[str, Any]]) -> dict[str, float]:
    """Fingerprint coverage across ingested sessions (production lens)."""
    sessions_with_fp = sum(1 for e in entries if e.get("fingerprints"))
    total = max(len(entries), 1)
    unique_fps = {
        fp["fp_id"]
        for e in entries
        for fp in e.get("fingerprints", [])
    }
    return {
        "session_coverage": round(sessions_with_fp / total, 3),
        "unique_fingerprints": float(len(unique_fps)),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Production ingest log utility (read-only observer)")
    parser.add_argument("--flush", action="store_true", help="Flush pending buffered entries")
    parser.add_argument("--stats", action="store_true", help="Show ingest log statistics")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH)
    args = parser.parse_args(argv)

    ingestor = ProductionIngestor(args.log)
    if args.flush:
        count = ingestor.flush()
        print(f"Flushed {count} pending entries")
    if args.stats or not args.flush:
        entries = ingestor.load_entries()
        cov = production_coverage(entries)
        print(f"=== Production Ingest Log ===")
        print(f"path: {args.log}")
        print(f"entries: {len(entries)}")
        print(f"pending buffer: {ingestor.pending_count}")
        print(f"session_coverage: {cov['session_coverage']:.0%}")
        print(f"unique_fingerprints: {int(cov['unique_fingerprints'])}")
        print(f"affects_runtime: {affects_runtime_decision()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
