"""Failure Taxonomy Layer v1 — classify, trace, readiness score."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from persona_ai.core.types import PersonalityProfile, SpeakAction, clamp
from persona_ai.sim.drift_harness import DriftMetrics, SessionReport, TurnRecord


class FailureDomain(str, Enum):
    BDV = "bdv"
    COHERENCE = "coherence"
    LLM = "llm"
    ARC = "arc"
    POLICY = "policy"
    SESSION = "session"
    BENIGN = "benign"


class FailureSeverity(str, Enum):
    STRUCTURAL = "structural"
    DEGRADED = "degraded"
    BENIGN = "benign"


class FailureClass(str, Enum):
    # BDV — decision kernel
    BDV_MISFIRE = "bdv_misfire"
    BDV_OVER_RESPONSIVE = "bdv_over_responsive"
    BDV_UNDER_RESPONSIVE = "bdv_under_responsive"
    BDV_SILENCE_MISS = "bdv_silence_miss"
    BDV_DEFER_MISS = "bdv_defer_miss"
    BDV_MECHANICAL_PATTERN = "bdv_mechanical_pattern"

    # Coherence — identity binding
    COHERENCE_WARMTH_JUMP = "coherence_warmth_jump"
    COHERENCE_ANCHOR_DRIFT = "coherence_anchor_drift"
    COHERENCE_FLATLINE = "coherence_flatline"

    # LLM — renderer surface
    LLM_OVERREACH = "llm_overreach"
    LLM_CPS_SPIKE = "llm_cps_spike"
    LLM_WORD_OVERFLOW = "llm_word_overflow"
    LLM_EMPTY_RESPONSE = "llm_empty_response"
    LLM_ACK_BYPASS = "llm_ack_bypass"

    # Arc — trajectory
    ARC_WARMTH_MISALIGN = "arc_warmth_misalign"
    ARC_PHASE_STALL = "arc_phase_stall"

    # Policy — hard gate (v0 placeholder)
    POLICY_WOULD_BLOCK = "policy_would_block"

    # Benign
    BENIGN_WEIRDNESS = "benign_weirdness"


@dataclass
class FailureEvent:
    turn_index: int | None
    domain: FailureDomain
    failure_class: FailureClass
    severity: FailureSeverity
    message: str
    evidence: dict = field(default_factory=dict)
    actionable: str = ""
    tag: str = ""


@dataclass
class FailureReport:
    events: list[FailureEvent]
    by_domain: dict[str, int]
    by_class: dict[str, int]
    by_severity: dict[str, int]
    structural_count: int
    degraded_count: int
    benign_count: int
    readiness_score: float
    readiness_grade: str
    primary_weakness: str | None = None
    debug_trace: str = ""
    causal: Any = None  # CausalReport when enriched via enrich_with_causality()
    counterfactual: Any = None  # CounterfactualReport when enriched
    intervention_graph: Any = None  # InterventionGraphReport when enriched
    intervention_policy: Any = None  # PolicyReport when enriched
    intervention_learning: Any = None  # LearningReport when enriched
    fingerprints: Any = None  # FingerprintReport when enriched


# --- turn-level classifiers ---

def _warmth_step_event(prev: TurnRecord, curr: TurnRecord, limit: float = 0.15) -> FailureEvent | None:
    step = abs(curr.effective_warmth - prev.effective_warmth)
    if step <= limit:
        return None
    severity = FailureSeverity.STRUCTURAL if step > 0.2 else FailureSeverity.DEGRADED
    return FailureEvent(
        turn_index=curr.index,
        domain=FailureDomain.COHERENCE,
        failure_class=FailureClass.COHERENCE_WARMTH_JUMP,
        severity=severity,
        message=f"Warmth jumped {step:.3f} (limit {limit:.2f})",
        evidence={"step": step, "prev": prev.effective_warmth, "curr": curr.effective_warmth},
        actionable="Check IdentityAnchor.max_drift_per_turn and BDV tone_shift exceptions.",
    )


def _turn_llm_events(turn: TurnRecord, max_words: int = 70) -> list[FailureEvent]:
    events: list[FailureEvent] = []
    if turn.cps_score > 0:
        events.append(
            FailureEvent(
                turn_index=turn.index,
                domain=FailureDomain.LLM,
                failure_class=FailureClass.LLM_CPS_SPIKE,
                severity=FailureSeverity.DEGRADED,
                message=f"CPS chatbot phrase detected (score {turn.cps_score:.2f})",
                evidence={"cps_score": turn.cps_score, "hits": turn.cps_hits},
                actionable="Tighten prompt_fragments; add post-gen CPS rewrite or denylist.",
            )
        )
    if turn.text and len(turn.text.split()) > max_words:
        events.append(
            FailureEvent(
                turn_index=turn.index,
                domain=FailureDomain.LLM,
                failure_class=FailureClass.LLM_WORD_OVERFLOW,
                severity=FailureSeverity.DEGRADED,
                message=f"Output {len(turn.text.split())} words exceeds budget ~{max_words}",
                evidence={"word_count": len(turn.text.split())},
                actionable="Enforce max_tokens / truncate post-gen; verify VoiceDirective.max_words in prompt.",
            )
        )
    if turn.speak in (SpeakAction.SILENCE, SpeakAction.DEFER) and turn.text:
        events.append(
            FailureEvent(
                turn_index=turn.index,
                domain=FailureDomain.LLM,
                failure_class=FailureClass.LLM_OVERREACH,
                severity=FailureSeverity.STRUCTURAL,
                message=f"{turn.speak.value} produced text — renderer ignored BDV",
                evidence={"speak": turn.speak.value, "text_preview": turn.text[:80]},
                actionable="Verify render() early exit; ensure adapter not called for SILENCE/DEFER.",
            )
        )
    if turn.speak == SpeakAction.RESPOND and turn.llm_called and not turn.text:
        events.append(
            FailureEvent(
                turn_index=turn.index,
                domain=FailureDomain.LLM,
                failure_class=FailureClass.LLM_EMPTY_RESPONSE,
                severity=FailureSeverity.STRUCTURAL,
                message="RESPOND requested but LLM returned empty",
                evidence={"speak": turn.speak.value},
                actionable="Check adapter error handling and max_tokens floor.",
            )
        )
    return events


def _arc_turn_event(turn: TurnRecord) -> FailureEvent | None:
    gap = abs(turn.effective_warmth - turn.arc_warmth)
    if gap <= 0.35:
        return None
    return FailureEvent(
        turn_index=turn.index,
        domain=FailureDomain.ARC,
        failure_class=FailureClass.ARC_WARMTH_MISALIGN,
        severity=FailureSeverity.BENIGN,
        message=f"Expression warmth diverges from arc warmth (Δ={gap:.2f})",
        evidence={"effective_warmth": turn.effective_warmth, "arc_warmth": turn.arc_warmth},
        actionable="Review arc.relational_warmth update rate vs personality shift_delta.",
        tag="benign_drift",
    )


def classify_contract_failure(
    turn_index: int,
    tag: str,
    violation: str,
    turn: TurnRecord,
    expected_speak: SpeakAction | None = None,
) -> FailureEvent:
    v = violation.lower()
    actual = turn.speak

    if "expected no output" in v or "silent action produced text" in v:
        if turn.text and actual in (SpeakAction.SILENCE, SpeakAction.DEFER):
            return FailureEvent(
                turn_index=turn_index,
                domain=FailureDomain.LLM,
                failure_class=FailureClass.LLM_OVERREACH,
                severity=FailureSeverity.STRUCTURAL,
                message=violation,
                evidence={"speak": actual.value, "tag": tag},
                actionable="Renderer must return None for SILENCE/DEFER — check pipeline.",
                tag=tag,
            )
        return FailureEvent(
            turn_index=turn_index,
            domain=FailureDomain.BDV,
            failure_class=_bdv_miss_class(expected_speak),
            severity=FailureSeverity.STRUCTURAL,
            message=violation,
            evidence={"actual": actual.value, "expected": expected_speak.value if expected_speak else None, "tag": tag},
            actionable="Review interpret.py heuristics and pressure thresholds for this input shape.",
            tag=tag,
        )

    if "expected" in v and "got" in v:
        fc = _bdv_miss_class(expected_speak)
        sev = FailureSeverity.STRUCTURAL if expected_speak in (SpeakAction.SILENCE, SpeakAction.DEFER) else FailureSeverity.DEGRADED
        return FailureEvent(
            turn_index=turn_index,
            domain=FailureDomain.BDV,
            failure_class=fc,
            severity=sev,
            message=violation,
            evidence={"actual": actual.value, "expected": expected_speak.value if expected_speak else None, "tag": tag},
            actionable="Add/adjust intent rule or mixed-intent priority in interpret.py.",
            tag=tag,
        )

    if "not in" in v:
        return FailureEvent(
            turn_index=turn_index,
            domain=FailureDomain.BDV,
            failure_class=FailureClass.BDV_MISFIRE,
            severity=FailureSeverity.DEGRADED,
            message=violation,
            evidence={"actual": actual.value, "tag": tag},
            actionable="Ambiguous input — widen allow_speak or refine heuristic for this archetype.",
            tag=tag,
        )

    if "respond with no text" in v:
        return FailureEvent(
            turn_index=turn_index,
            domain=FailureDomain.LLM,
            failure_class=FailureClass.LLM_EMPTY_RESPONSE,
            severity=FailureSeverity.STRUCTURAL,
            message=violation,
            evidence={"tag": tag},
            actionable="Check LLM adapter and API errors.",
            tag=tag,
        )

    if "ack_only should use template" in v:
        return FailureEvent(
            turn_index=turn_index,
            domain=FailureDomain.LLM,
            failure_class=FailureClass.LLM_ACK_BYPASS,
            severity=FailureSeverity.DEGRADED,
            message=violation,
            evidence={"tag": tag},
            actionable="Short-circuit ACK path in render().",
            tag=tag,
        )

    return FailureEvent(
        turn_index=turn_index,
        domain=FailureDomain.BDV,
        failure_class=FailureClass.BDV_MISFIRE,
        severity=FailureSeverity.DEGRADED,
        message=violation,
        evidence={"tag": tag},
        actionable="Inspect contract violation and map to interpret/engine rule.",
        tag=tag,
    )


def _bdv_miss_class(expected: SpeakAction | None) -> FailureClass:
    if expected == SpeakAction.SILENCE:
        return FailureClass.BDV_SILENCE_MISS
    if expected == SpeakAction.DEFER:
        return FailureClass.BDV_DEFER_MISS
    if expected == SpeakAction.RESPOND:
        return FailureClass.BDV_UNDER_RESPONSIVE
    if expected == SpeakAction.ACK_ONLY:
        return FailureClass.BDV_OVER_RESPONSIVE
    return FailureClass.BDV_MISFIRE


# --- session-level classifiers ---

def _drift_session_events(metrics: DriftMetrics) -> list[FailureEvent]:
    events: list[FailureEvent] = []
    drift_limit = 0.15

    if metrics.max_warmth_step > drift_limit:
        events.append(
            FailureEvent(
                turn_index=None,
                domain=FailureDomain.COHERENCE,
                failure_class=FailureClass.COHERENCE_WARMTH_JUMP,
                severity=FailureSeverity.STRUCTURAL if metrics.max_warmth_step > 0.2 else FailureSeverity.DEGRADED,
                message=f"Session max warmth step {metrics.max_warmth_step:.3f}",
                evidence={"max_step": metrics.max_warmth_step},
                actionable="Tighten coherence bind or reduce BDV tone_shift magnitude.",
            )
        )

    if metrics.warmth_range > 0.4:
        events.append(
            FailureEvent(
                turn_index=None,
                domain=FailureDomain.COHERENCE,
                failure_class=FailureClass.COHERENCE_ANCHOR_DRIFT,
                severity=FailureSeverity.STRUCTURAL,
                message=f"Warmth range {metrics.warmth_range:.3f} too wide",
                evidence={"range": metrics.warmth_range},
                actionable="Lower max_drift_per_turn or increase anchor EMA alpha stability.",
            )
        )
    elif metrics.warmth_range < 0.04 and metrics.turn_count >= 10:
        events.append(
            FailureEvent(
                turn_index=None,
                domain=FailureDomain.COHERENCE,
                failure_class=FailureClass.COHERENCE_FLATLINE,
                severity=FailureSeverity.DEGRADED,
                message="Warmth collapsed — entity feels flat",
                evidence={"range": metrics.warmth_range, "std": metrics.warmth_std},
                actionable="Allow controlled drift or arc warmth floor boost.",
            )
        )

    if metrics.anchor_range > 0.45:
        events.append(
            FailureEvent(
                turn_index=None,
                domain=FailureDomain.COHERENCE,
                failure_class=FailureClass.COHERENCE_ANCHOR_DRIFT,
                severity=FailureSeverity.STRUCTURAL,
                message=f"Anchor baseline drifted {metrics.anchor_range:.3f} over session",
                evidence={"anchor_range": metrics.anchor_range},
                actionable="Verify update_anchor persists; check anchor alpha.",
            )
        )

    if metrics.max_same_speak_streak >= 10:
        events.append(
            FailureEvent(
                turn_index=None,
                domain=FailureDomain.BDV,
                failure_class=FailureClass.BDV_MECHANICAL_PATTERN,
                severity=FailureSeverity.STRUCTURAL,
                message=f"Speak streak {metrics.max_same_speak_streak} — mechanical",
                evidence={"streak": metrics.max_same_speak_streak},
                actionable="Review pressure softmax spread; add arc silence bias.",
            )
        )

    respond_ratio = metrics.speak_counts.get(SpeakAction.RESPOND.value, 0) / max(metrics.turn_count, 1)
    if respond_ratio > 0.85 and metrics.turn_count >= 15:
        events.append(
            FailureEvent(
                turn_index=None,
                domain=FailureDomain.BDV,
                failure_class=FailureClass.BDV_OVER_RESPONSIVE,
                severity=FailureSeverity.STRUCTURAL,
                message=f"Over-responsive: {respond_ratio:.0%} RESPOND",
                evidence={"respond_ratio": respond_ratio},
                actionable="Raise silence/ack pressure for closure and vent archetypes.",
            )
        )

    return events


def _aggregate(events: list[FailureEvent]) -> FailureReport:
    by_domain: dict[str, int] = {}
    by_class: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    structural = degraded = benign = 0

    for e in events:
        by_domain[e.domain.value] = by_domain.get(e.domain.value, 0) + 1
        by_class[e.failure_class.value] = by_class.get(e.failure_class.value, 0) + 1
        by_severity[e.severity.value] = by_severity.get(e.severity.value, 0) + 1
        if e.severity == FailureSeverity.STRUCTURAL:
            structural += 1
        elif e.severity == FailureSeverity.DEGRADED:
            degraded += 1
        else:
            benign += 1

    score = _readiness_score(structural, degraded, benign, len(events))
    grade = _readiness_grade(score)
    weakness = _primary_weakness(by_domain, by_class)
    report = FailureReport(
        events=events,
        by_domain=by_domain,
        by_class=by_class,
        by_severity=by_severity,
        structural_count=structural,
        degraded_count=degraded,
        benign_count=benign,
        readiness_score=score,
        readiness_grade=grade,
        primary_weakness=weakness,
    )
    report.debug_trace = format_debug_trace(report)
    return report


def _readiness_score(structural: int, degraded: int, benign: int, total: int) -> float:
    if total == 0:
        return 100.0
    penalty = structural * 18 + degraded * 7 + benign * 2
    return clamp(100.0 - penalty, 0.0, 100.0)


def _readiness_grade(score: float) -> str:
    if score >= 85:
        return "v2_ready"
    if score >= 65:
        return "v1_stable"
    if score >= 40:
        return "v1_caution"
    return "v1_block"


def _primary_weakness(by_domain: dict[str, int], by_class: dict[str, int]) -> str | None:
    if not by_domain:
        return None
    domain = max(by_domain, key=by_domain.get)  # type: ignore[arg-type]
    top_class = max(by_class, key=by_class.get) if by_class else None  # type: ignore[arg-type]
    return f"{domain}" + (f"/{top_class}" if top_class else "")


def analyze_session(
    session: SessionReport,
    profile: PersonalityProfile | None = None,
) -> FailureReport:
    """Classify failures from turn records + drift metrics."""
    events: list[FailureEvent] = []
    turns = session.turns

    for i, turn in enumerate(turns):
        events.extend(_turn_llm_events(turn))
        arc_ev = _arc_turn_event(turn)
        if arc_ev:
            events.append(arc_ev)
        if i > 0:
            step_ev = _warmth_step_event(turns[i - 1], turn)
            if step_ev:
                events.append(step_ev)

    events.extend(_drift_session_events(session.metrics))
    return _aggregate(_dedupe_events(events))


def analyze_drift(session: SessionReport) -> FailureReport:
    return _aggregate(_drift_session_events(session.metrics))


def analyze_smoke(
    session: SessionReport,
    contracts: list,
    specs: list | None = None,
) -> FailureReport:
    """Full taxonomy pass: turns + drift + behavior contracts."""
    events = analyze_session(session).events

    for contract in contracts:
        if contract.passed:
            continue
        idx = contract.turn_index
        turn = session.turns[idx] if idx < len(session.turns) else None
        if turn is None:
            continue
        expected = None
        if specs and idx < len(specs):
            expected = getattr(specs[idx], "expect_speak", None)
        events.append(
            classify_contract_failure(idx, contract.tag, contract.violation, turn, expected)
        )

    return _aggregate(_dedupe_events(events))


def _dedupe_events(events: list[FailureEvent]) -> list[FailureEvent]:
    seen: set[tuple] = set()
    out: list[FailureEvent] = []
    for e in events:
        key = (e.turn_index, e.failure_class.value, e.message[:60])
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def format_debug_trace(report: FailureReport) -> str:
    lines = [
        f"=== Failure Taxonomy | readiness={report.readiness_score:.0f} ({report.readiness_grade}) ===",
        f"Structural: {report.structural_count} | Degraded: {report.degraded_count} | Benign: {report.benign_count}",
    ]
    if report.primary_weakness:
        lines.append(f"Primary weakness: {report.primary_weakness}")
    if report.by_domain:
        lines.append(f"By domain: {report.by_domain}")
    if not report.events:
        lines.append("No failures classified.")
        return "\n".join(lines)

    lines.append("--- events ---")
    for e in report.events:
        turn = f"t{e.turn_index}" if e.turn_index is not None else "session"
        lines.append(
            f"  [{turn}] {e.severity.value.upper():10s} {e.domain.value}/{e.failure_class.value}"
        )
        lines.append(f"         {e.message}")
        if e.actionable:
            lines.append(f"         -> {e.actionable}")
    return "\n".join(lines)
