"""Failure signature fingerprinting v1.1 — stable, lossy bug identity across runs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from persona_ai.core.types import SpeakAction
from persona_ai.diagnostics.causal_graph import CausalNode, CausalReport
from persona_ai.diagnostics.failure_taxonomy import FailureClass, FailureEvent, FailureReport
from persona_ai.sim.drift_harness import SessionReport, TurnRecord

# Canonical hash field order (never reorder).
HASH_FIELD_ORDER = ("failure_class", "root", "ctx", "mismatch")

# Interpret reason codes eligible for context (exclude BDV speak labels).
INTERPRET_CTX_CODES = (
    "indirect_instruction_chain",
    "trailing_hesitation",
    "incomplete_utterance",
    "mixed_intent",
    "mixed_or_confusion_priority",
    "confusion_signal",
    "closure_ack",
    "rhetorical_vent",
    "user_venting",
    "direct_question",
    "command",
    "frustrated_dismissal",
    "ack_or_backchannel",
)

# Dominant ctx wins when multiple signals present (lower index = higher priority).
CTX_PRIORITY: tuple[str, ...] = (
    "instructional_intent",
    "mixed_intent",
    "trailing_ellipsis",
    "closure_context",
    "frustrated_dismissal",
    "vent_context",
    "rhetorical_vent",
    "session_mechanical",
    "session_over_responsive",
    "session_anchor_drift",
    "session_flatline",
    "session_warmth_jump",
    "session_generic",
    "generic",
)

SPEAK_REASON_CODES = frozenset(a.value.lower() for a in SpeakAction)

# Raw token -> canonical ctx bucket (hash uses bucket only).
CTX_ALIASES: dict[str, str] = {
    "trailing_hesitation": "trailing_ellipsis",
    "incomplete_utterance": "trailing_ellipsis",
    "trailing_defer": "trailing_ellipsis",
    "indirect_chain": "instructional_intent",
    "indirect_instruction_chain": "instructional_intent",
    "instruction_chain": "instructional_intent",
    "instruction_request": "instructional_intent",
    "direct_question": "instructional_intent",
    "command": "instructional_intent",
    "trailing_confusion": "mixed_intent",
    "mixed_emotion_question": "mixed_intent",
    "mixed_or_confusion_priority": "mixed_intent",
    "confusion_signal": "mixed_intent",
    "closure_after_long": "closure_context",
    "closure_ack": "closure_context",
    "vent_rhetorical": "rhetorical_vent",
    "sarcasm_vent": "vent_context",
    "sarcasm_dismiss": "vent_context",
    "sarcasm_lite": "vent_context",
    "user_venting": "vent_context",
}

# Intent-related roots collapse to one family for under-responsive failures.
ROOT_CAUSE_ALIASES: dict[str, str] = {
    "interpret.intent_need": "interpret.intent_resolution",
    "interpret.requires_response": "interpret.intent_resolution",
    "interpret.is_direct_question": "interpret.intent_resolution",
    "interpret.is_command": "interpret.intent_resolution",
}

ROOT_CAUSE_FALLBACK: dict[FailureClass, str] = {
    FailureClass.BDV_UNDER_RESPONSIVE: "interpret.intent_resolution",
    FailureClass.BDV_DEFER_MISS: "interpret.incompleteness_score",
    FailureClass.BDV_SILENCE_MISS: "interpret.closure_ack",
    FailureClass.BDV_OVER_RESPONSIVE: "pressure.speak_pressure",
    FailureClass.BDV_MISFIRE: "arbitration.softmax",
    FailureClass.BDV_MECHANICAL_PATTERN: "arbitration.softmax_collapse",
    FailureClass.COHERENCE_WARMTH_JUMP: "coherence.warmth_step",
    FailureClass.COHERENCE_ANCHOR_DRIFT: "coherence.anchor_ema",
    FailureClass.COHERENCE_FLATLINE: "coherence.warmth_flatline",
    FailureClass.LLM_OVERREACH: "llm.render_bypass",
    FailureClass.LLM_CPS_SPIKE: "llm.cps_score",
    FailureClass.LLM_WORD_OVERFLOW: "llm.word_count",
    FailureClass.LLM_EMPTY_RESPONSE: "llm.generation",
    FailureClass.LLM_ACK_BYPASS: "llm.template_bypass",
    FailureClass.ARC_WARMTH_MISALIGN: "arc.relational_warmth",
    FailureClass.ARC_PHASE_STALL: "arc.phase",
}

SESSION_CTX: dict[FailureClass, str] = {
    FailureClass.BDV_MECHANICAL_PATTERN: "session_mechanical",
    FailureClass.BDV_OVER_RESPONSIVE: "session_over_responsive",
    FailureClass.COHERENCE_ANCHOR_DRIFT: "session_anchor_drift",
    FailureClass.COHERENCE_FLATLINE: "session_flatline",
    FailureClass.COHERENCE_WARMTH_JUMP: "session_warmth_jump",
}

# SpeakAction enum values + common aliases for mismatch normalization.
SPEAK_ACTION_ALIASES: dict[str, str] = {
    "ACK": "ACK_ONLY",
    "ACKONLY": "ACK_ONLY",
    "SILENT": "SILENCE",
    "NONE": "SILENCE",
    "WAIT": "DEFER",
    "HOLD": "DEFER",
    "REPLY": "RESPOND",
    "ANSWER": "RESPOND",
}

VALID_SPEAK_ACTIONS = frozenset(a.value for a in SpeakAction)

INDIRECT_SUBTYPE_TOKENS = frozenset(
    {"indirect_instruction_chain", "indirect_chain", "trailing_confusion"}
)
DIRECT_SUBTYPE_TOKENS = frozenset(
    {"direct_question", "command", "instruction_chain", "instruction_request"}
)


@dataclass
class FailureFingerprint:
    """Stable identity for a failure archetype (lossy compression)."""

    fingerprint_id: str
    semantic_key: str
    display: str
    failure_class: str
    root_cause: str
    context_signature: str
    mismatch: str | None
    normalized: str
    metadata: dict[str, str | list[str]] = field(default_factory=dict)


@dataclass
class FingerprintedFailure:
    failure: FailureEvent
    fingerprint: FailureFingerprint
    turn_index: int | None = None
    turn_tag: str = ""


@dataclass
class FingerprintRegistryEntry:
    fingerprint_id: str
    display: str
    semantic_key: str
    first_seen_at: str
    last_seen_at: str
    occurrence_count: int = 0
    status: str = "open"  # open | closed
    runs_seen: list[str] = field(default_factory=list)


@dataclass
class FingerprintReport:
    items: list[FingerprintedFailure]
    unique_ids: list[str]
    by_fingerprint: dict[str, int]
    new_vs_known: dict[str, int] = field(default_factory=dict)
    debug_trace: str = ""


def _normalize_ctx_token(token: str) -> str:
    return CTX_ALIASES.get(token, token)


def _collect_ctx_candidates(failure: FailureEvent, turn: TurnRecord | None) -> list[str]:
    candidates: list[str] = []

    if turn and turn.reason_codes:
        for code in turn.reason_codes:
            if code in SPEAK_REASON_CODES:
                continue
            if code in INTERPRET_CTX_CODES or code in CTX_ALIASES:
                candidates.append(_normalize_ctx_token(code))

    if failure.tag:
        candidates.append(_normalize_ctx_token(failure.tag))

    if turn and turn.context:
        ctx = turn.context
        if ctx.is_mixed_intent or ctx.is_confusion_signal:
            candidates.append("mixed_intent")
        if ctx.is_closure_ack:
            candidates.append("closure_context")
        if ctx.is_vent:
            candidates.append("vent_context")
        if ctx.incompleteness_score >= 0.5:
            candidates.append("trailing_ellipsis")

    if failure.turn_index is None:
        candidates.append(SESSION_CTX.get(failure.failure_class, "session_generic"))

    if not candidates:
        candidates.append("generic")

    # Dedupe preserving first-seen order.
    seen: set[str] = set()
    ordered: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def _pick_dominant_ctx(candidates: list[str]) -> str:
    priority_index = {name: i for i, name in enumerate(CTX_PRIORITY)}
    return min(candidates, key=lambda c: priority_index.get(c, len(CTX_PRIORITY)))


def _normalize_root_cause(root: str, failure_class: FailureClass) -> str:
    if failure_class in (FailureClass.BDV_UNDER_RESPONSIVE, FailureClass.BDV_MISFIRE):
        if root in ROOT_CAUSE_ALIASES:
            return ROOT_CAUSE_ALIASES[root]
        if root.startswith("interpret.intent") or root.startswith("interpret.is_"):
            return "interpret.intent_resolution"
    return ROOT_CAUSE_ALIASES.get(root, root)


def _instructional_subtype(raw_tokens: list[str]) -> str | None:
    if not any(_normalize_ctx_token(t) == "instructional_intent" for t in raw_tokens):
        return None
    has_indirect = any(t in INDIRECT_SUBTYPE_TOKENS for t in raw_tokens)
    has_direct = any(t in DIRECT_SUBTYPE_TOKENS for t in raw_tokens)
    if has_indirect and not has_direct:
        return "indirect_chain"
    if has_direct and not has_indirect:
        return "direct"
    if has_indirect and has_direct:
        return "mixed"
    return "direct"


def _extract_context(failure: FailureEvent, turn: TurnRecord | None) -> tuple[str, dict[str, str | list[str]]]:
    raw_tokens: list[str] = []
    if turn and turn.reason_codes:
        raw_tokens.extend(
            c for c in turn.reason_codes if c not in SPEAK_REASON_CODES
        )
    if failure.tag:
        raw_tokens.append(failure.tag)

    candidates = _collect_ctx_candidates(failure, turn)
    dominant = _pick_dominant_ctx(candidates)

    metadata: dict[str, str | list[str]] = {}
    hints = [c for c in candidates if c != dominant]
    if hints:
        metadata["ctx_hints"] = hints

    subtype = _instructional_subtype(raw_tokens)
    if dominant == "instructional_intent" and subtype:
        metadata["ctx_subtype"] = subtype

    return dominant, metadata


def _normalize_speak_token(value: str) -> str:
    cleaned = value.strip().upper()
    cleaned = cleaned.replace("\u2192", "->").replace("\u2014", "-")
    cleaned = re.sub(r"[^A-Z_>]", "", cleaned.replace("-", "_"))
    if cleaned in SPEAK_ACTION_ALIASES:
        cleaned = SPEAK_ACTION_ALIASES[cleaned]
    if cleaned in VALID_SPEAK_ACTIONS:
        return cleaned
    # Last-resort: strip trailing _ONLY etc.
    for action in VALID_SPEAK_ACTIONS:
        if cleaned == action.replace("_", ""):
            return action
    return cleaned


def _extract_mismatch(failure: FailureEvent) -> str | None:
    actual = failure.evidence.get("actual")
    expected = failure.evidence.get("expected")
    if not actual or not expected:
        return None
    act = _normalize_speak_token(str(actual))
    exp = _normalize_speak_token(str(expected))
    if act not in VALID_SPEAK_ACTIONS or exp not in VALID_SPEAK_ACTIONS:
        return f"{act}->{exp}"
    return f"{act}->{exp}"


def _resolve_root_cause(failure: FailureEvent, causal_node: CausalNode | None) -> str:
    if causal_node and causal_node.root_cause:
        raw = causal_node.root_cause
    else:
        raw = ROOT_CAUSE_FALLBACK.get(failure.failure_class, "unknown.insufficient_context")
    return _normalize_root_cause(raw, failure.failure_class)


def _root_short_label(root_cause: str) -> str:
    signal = root_cause.split(".")[-1]
    return signal.upper()


def _build_normalized_string(
    failure_class: str,
    root_cause: str,
    context_signature: str,
    mismatch: str | None,
) -> str:
    """Canonical, deterministic hash input."""
    parts = [
        failure_class,
        f"root={root_cause}",
        f"ctx={context_signature}",
    ]
    if mismatch:
        parts.append(f"mismatch={mismatch}")
    return "|".join(parts)


def build_fingerprint(
    failure: FailureEvent,
    *,
    causal_node: CausalNode | None = None,
    turn: TurnRecord | None = None,
) -> FailureFingerprint:
    failure_class = failure.failure_class.value
    root_cause = _resolve_root_cause(failure, causal_node)
    context_signature, metadata = _extract_context(failure, turn)
    mismatch = _extract_mismatch(failure)
    normalized = _build_normalized_string(failure_class, root_cause, context_signature, mismatch)

    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]
    fingerprint_id = f"fp_{digest}"
    semantic_key = (
        f"FP::{failure_class.upper()}::{context_signature.upper()}::{_root_short_label(root_cause)}"
    )

    return FailureFingerprint(
        fingerprint_id=fingerprint_id,
        semantic_key=semantic_key,
        display=normalized,
        failure_class=failure_class,
        root_cause=root_cause,
        context_signature=context_signature,
        mismatch=mismatch,
        normalized=normalized,
        metadata=metadata,
    )


def _causal_index(causal: CausalReport | None) -> dict[tuple[int | None, str], CausalNode]:
    if not causal:
        return {}
    out: dict[tuple[int | None, str], CausalNode] = {}
    for node in causal.nodes:
        f = node.failure
        out[(f.turn_index, f.failure_class.value)] = node
    return out


def build_fingerprint_report(
    failure_report: FailureReport,
    session: SessionReport,
) -> FingerprintReport:
    causal_map = _causal_index(failure_report.causal)
    items: list[FingerprintedFailure] = []
    by_fp: dict[str, int] = {}

    for failure in failure_report.events:
        turn: TurnRecord | None = None
        if failure.turn_index is not None and failure.turn_index < len(session.turns):
            turn = session.turns[failure.turn_index]
        node = causal_map.get((failure.turn_index, failure.failure_class.value))
        fp = build_fingerprint(failure, causal_node=node, turn=turn)
        items.append(
            FingerprintedFailure(
                failure=failure,
                fingerprint=fp,
                turn_index=failure.turn_index,
                turn_tag=failure.tag,
            )
        )
        by_fp[fp.fingerprint_id] = by_fp.get(fp.fingerprint_id, 0) + 1

    unique_ids = list(dict.fromkeys(item.fingerprint.fingerprint_id for item in items))
    report = FingerprintReport(
        items=items,
        unique_ids=unique_ids,
        by_fingerprint=by_fp,
    )
    report.debug_trace = format_fingerprint_trace(report)
    return report


def format_fingerprint_trace(report: FingerprintReport) -> str:
    if not report.items:
        return "=== Failure Fingerprints | none (clean run) ==="

    lines = [
        "=== Failure Fingerprints | stable signatures (v1.1) ===",
        f"Unique: {len(report.unique_ids)} | Total events: {len(report.items)}",
    ]
    if report.by_fingerprint:
        ranked = sorted(report.by_fingerprint.items(), key=lambda x: -x[1])
        lines.append("By fingerprint: " + ", ".join(f"{k}x{v}" for k, v in ranked))

    seen: set[str] = set()
    for item in report.items:
        fp = item.fingerprint
        if fp.fingerprint_id in seen:
            continue
        seen.add(fp.fingerprint_id)
        turn = f"t{item.turn_index}" if item.turn_index is not None else "session"
        lines.append(f"\n[{turn}] {fp.fingerprint_id}")
        lines.append(f"  semantic: {fp.semantic_key}")
        lines.append(f"  {fp.display}")
        if fp.metadata:
            meta_parts = []
            if "ctx_subtype" in fp.metadata:
                meta_parts.append(f"subtype={fp.metadata['ctx_subtype']}")
            if "ctx_hints" in fp.metadata:
                meta_parts.append(f"hints={fp.metadata['ctx_hints']}")
            if meta_parts:
                lines.append(f"  meta: {', '.join(meta_parts)}")

    return "\n".join(lines)


class FingerprintRegistry:
    """Cross-run memory for fingerprint recurrence and regression detection."""

    DEFAULT_PATH = Path(".persona_ai/fingerprint_registry.json")

    def __init__(self, store_path: Path | None = None):
        self.store_path = store_path or self.DEFAULT_PATH
        self.entries: dict[str, FingerprintRegistryEntry] = {}
        if self.store_path.exists():
            self._load()

    def _load(self) -> None:
        raw = json.loads(self.store_path.read_text(encoding="utf-8"))
        for item in raw.get("entries", []):
            entry = FingerprintRegistryEntry(**item)
            self.entries[entry.fingerprint_id] = entry

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [asdict(e) for e in self.entries.values()]}
        self.store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def record_run(
        self,
        report: FingerprintReport,
        *,
        run_id: str,
        script_name: str = "",
    ) -> dict[str, int]:
        """Ingest fingerprints from a diagnostic run. Returns new vs known counts."""
        now = datetime.now(timezone.utc).isoformat()
        run_label = f"{script_name}:{run_id}" if script_name else run_id
        new_count = known_count = 0

        seen_this_run: set[str] = set()
        for item in report.items:
            fp = item.fingerprint
            if fp.fingerprint_id in seen_this_run:
                continue
            seen_this_run.add(fp.fingerprint_id)

            entry = self.entries.get(fp.fingerprint_id)
            if entry is None:
                entry = FingerprintRegistryEntry(
                    fingerprint_id=fp.fingerprint_id,
                    display=fp.display,
                    semantic_key=fp.semantic_key,
                    first_seen_at=now,
                    last_seen_at=now,
                    occurrence_count=0,
                    status="open",
                    runs_seen=[],
                )
                self.entries[fp.fingerprint_id] = entry
                new_count += 1
            else:
                known_count += 1

            entry.occurrence_count += 1
            entry.last_seen_at = now
            if run_label not in entry.runs_seen:
                entry.runs_seen.append(run_label)
                if len(entry.runs_seen) > 20:
                    entry.runs_seen = entry.runs_seen[-20:]

        report.new_vs_known = {"new": new_count, "known": known_count}
        return report.new_vs_known

    def mark_closed(self, fingerprint_id: str) -> None:
        if fingerprint_id in self.entries:
            self.entries[fingerprint_id].status = "closed"

    def is_regression(self, fingerprint_id: str) -> bool:
        entry = self.entries.get(fingerprint_id)
        return entry is not None and entry.status == "closed"


def enrich_with_fingerprints(
    failure_report: FailureReport,
    session: SessionReport,
    *,
    registry: FingerprintRegistry | None = None,
    run_id: str | None = None,
    script_name: str = "",
    persist_registry: bool = False,
) -> FailureReport:
    """Attach fingerprint report; optionally record to cross-run registry."""
    fp_report = build_fingerprint_report(failure_report, session)
    if registry is not None and run_id:
        registry.record_run(fp_report, run_id=run_id, script_name=script_name)
        if persist_registry:
            registry.save()

    failure_report.fingerprints = fp_report
    failure_report.debug_trace = failure_report.debug_trace + "\n\n" + fp_report.debug_trace
    return failure_report
