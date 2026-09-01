"""OpenAI smoke test harness — behavior consistency under semantic chaos."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

from persona_ai.core.types import PersonalityProfile, SpeakAction
from persona_ai.diagnostics.failure_fingerprint import enrich_with_fingerprints, FingerprintRegistry
from persona_ai.diagnostics.causal_graph import enrich_with_causality
from persona_ai.diagnostics.counterfactual import enrich_with_counterfactuals
from persona_ai.diagnostics.intervention_learning import enrich_with_learning
from persona_ai.diagnostics.intervention_graph import enrich_with_intervention_graph
from persona_ai.diagnostics.failure_taxonomy import FailureReport, analyze_smoke, format_debug_trace
from persona_ai.llm.adapter import LLMAdapter, OpenAILLMAdapter, default_adapter, get_adapter
from persona_ai.sim.adversarial_scripts import ADVERSARIAL_SCRIPTS, AdversarialTurn
from persona_ai.sim.drift_harness import (
    DriftMetrics,
    SessionReport,
    SessionSimulator,
    classify_grade,
    compute_drift_metrics,
)


@dataclass
class BehaviorContract:
    turn_index: int
    tag: str
    passed: bool
    violation: str = ""


@dataclass
class SmokeMetrics:
    drift: DriftMetrics
    cps_spike_count: int
    cps_max: float
    cps_turns: list[int]
    behavior_contracts: list[BehaviorContract]
    contract_pass_rate: float
    llm_turns: int
    word_overflow_count: int
    silence_correct: int
    silence_expected: int
    grade: str
    notes: list[str] = field(default_factory=list)


@dataclass
class SmokeReport:
    script_name: str
    adapter: str
    session: SessionReport
    smoke: SmokeMetrics
    failure: FailureReport | None = None


@dataclass
class ComparisonReport:
    script_name: str
    gemini: SmokeReport
    openai: SmokeReport
    grade_parity: bool
    contract_parity: bool
    anchor_delta: float


def _check_turn_contract(turn_index: int, spec: AdversarialTurn, record) -> BehaviorContract:
    speak = record.speak
    text = record.text

    if spec.expect_no_output or spec.expect_speak in (SpeakAction.SILENCE, SpeakAction.DEFER):
        if text is not None:
            return BehaviorContract(turn_index, spec.tag, False, f"expected no output, got: {text[:40]!r}")
        if spec.expect_speak and speak != spec.expect_speak:
            return BehaviorContract(turn_index, spec.tag, False, f"expected {spec.expect_speak.value}, got {speak.value}")
        return BehaviorContract(turn_index, spec.tag, True)

    if spec.expect_speak and speak != spec.expect_speak:
        return BehaviorContract(turn_index, spec.tag, False, f"expected {spec.expect_speak.value}, got {speak.value}")

    if spec.allow_speak and speak not in spec.allow_speak:
        return BehaviorContract(
            turn_index,
            spec.tag,
            False,
            f"speak {speak.value} not in {[s.value for s in spec.allow_speak]}",
        )

    if speak in (SpeakAction.SILENCE, SpeakAction.DEFER) and text is not None:
        return BehaviorContract(turn_index, spec.tag, False, "silent action produced text")

    if speak == SpeakAction.RESPOND and record.llm_called and not text:
        return BehaviorContract(turn_index, spec.tag, False, "RESPOND with no text")

    if speak == SpeakAction.ACK_ONLY and not text and not record.llm_called:
        return BehaviorContract(turn_index, spec.tag, False, "ACK_ONLY produced no natural reply")

    return BehaviorContract(turn_index, spec.tag, True)


def compute_smoke_metrics(
    session: SessionReport,
    specs: list[AdversarialTurn],
    profile: PersonalityProfile,
) -> SmokeMetrics:
    drift = session.metrics if session.metrics.turn_count else compute_drift_metrics(session.turns, profile)
    notes = list(drift.notes)

    cps_turns = [t.index for t in session.turns if t.cps_score > 0]
    cps_max = max((t.cps_score for t in session.turns), default=0.0)

    contracts: list[BehaviorContract] = []
    for i, spec in enumerate(specs):
        if i >= len(session.turns):
            break
        contracts.append(_check_turn_contract(i, spec, session.turns[i]))

    passed = sum(1 for c in contracts if c.passed)
    pass_rate = passed / len(contracts) if contracts else 0.0

    silence_expected = sum(
        1 for s in specs[: len(session.turns)]
        if s.expect_speak == SpeakAction.SILENCE or s.expect_no_output
    )
    silence_correct = sum(
        1 for c in contracts if c.passed and session.turns[c.turn_index].speak == SpeakAction.SILENCE
    )

    word_overflow = 0
    llm_turns = 0
    for t in session.turns:
        if t.llm_called:
            llm_turns += 1
        if t.text and len(t.text.split()) > 75:
            word_overflow += 1
            notes.append(f"turn {t.index}: output >75 words")

    if cps_spike_count := len(cps_turns):
        notes.append(f"CPS spikes on turns {cps_turns}")
    if pass_rate < 0.7:
        notes.append(f"behavior contract pass rate {pass_rate:.0%}")

    stable = drift.identity_stable and pass_rate >= 0.7 and cps_max < 0.85
    mechanical = drift.mechanical_score + (1 - pass_rate) * 0.5 + min(1.0, cps_max)
    mechanical = min(1.0, mechanical / 2)
    grade = classify_grade(stable, mechanical, notes)
    if pass_rate < 0.5:
        grade = "C"

    return SmokeMetrics(
        drift=drift,
        cps_spike_count=cps_spike_count,
        cps_max=cps_max,
        cps_turns=cps_turns,
        behavior_contracts=contracts,
        contract_pass_rate=pass_rate,
        llm_turns=llm_turns,
        word_overflow_count=word_overflow,
        silence_correct=silence_correct,
        silence_expected=silence_expected,
        grade=grade,
        notes=notes,
    )


def run_smoke(
    script_name: str,
    adapter: LLMAdapter | None = None,
    profile: PersonalityProfile | None = None,
    session_id: str | None = None,
    *,
    record: bool = False,
    observe: bool = False,
    registry: FingerprintRegistry | None = None,
) -> SmokeReport:
    specs = ADVERSARIAL_SCRIPTS[script_name]
    profile = profile or PersonalityProfile()
    adapter = adapter or default_adapter()
    adapter_name = getattr(adapter, "model", type(adapter).__name__)

    sim = SessionSimulator(
        session_id or f"smoke-{script_name}-{adapter_name}",
        profile=profile,
        adapter=adapter,
    )

    for spec in specs:
        if spec.expect_speak == SpeakAction.SILENCE:
            sim.seed_long_assistant()
        sim.run_turn(spec.text)

    session = SessionReport(
        script_name=script_name,
        turns=list(sim.turns),
        metrics=compute_drift_metrics(sim.turns, profile),
    )
    smoke = compute_smoke_metrics(session, specs, profile)
    failure = analyze_smoke(session, smoke.behavior_contracts, specs)
    failure = enrich_with_causality(failure, session)
    failure = enrich_with_counterfactuals(failure, session)
    failure = enrich_with_intervention_graph(failure, session)
    failure = enrich_with_fingerprints(failure, session)
    failure = enrich_with_learning(failure, session)
    run_id = session_id or f"smoke-{script_name}-{adapter_name}"
    smoke_report = SmokeReport(
        script_name=script_name,
        adapter=str(adapter_name),
        session=session,
        smoke=smoke,
        failure=failure,
    )
    if record:
        from persona_ai.diagnostics.regression_dashboard import record_smoke_run

        reg = registry or FingerprintRegistry()
        record_smoke_run(smoke_report, run_id=run_id, registry=reg, persist=True)
    if observe:
        from persona_ai.diagnostics.production_ingest import get_ingestor

        get_ingestor().observe(smoke_report, session_id=run_id, source="smoke")
    return smoke_report


def compare_gemini_vs_openai(
    script_name: str,
) -> ComparisonReport:
    gemini = run_smoke(script_name, get_adapter("gemini"))
    openai = run_smoke(
        script_name,
        OpenAILLMAdapter(),
        session_id=f"openai-{script_name}",
    )
    gemini_anchor = gemini.session.metrics.anchor_values
    openai_anchor = openai.session.metrics.anchor_values
    anchor_delta = 0.0
    if gemini_anchor and openai_anchor:
        anchor_delta = abs(gemini_anchor[-1] - openai_anchor[-1])

    return ComparisonReport(
        script_name=script_name,
        gemini=gemini,
        openai=openai,
        grade_parity=gemini.smoke.grade in ("A", "B") and openai.smoke.grade in ("A", "B"),
        contract_parity=abs(gemini.smoke.contract_pass_rate - openai.smoke.contract_pass_rate) <= 0.3,
        anchor_delta=anchor_delta,
    )


def format_report(report: SmokeReport) -> str:
    m = report.smoke
    d = m.drift
    lines = [
        f"=== Smoke: {report.script_name} ({report.adapter}) ===",
        f"Grade: {m.grade} | Drift grade: {d.grade} | Contract pass: {m.contract_pass_rate:.0%}",
        f"Turns: {d.turn_count} | LLM turns: {m.llm_turns} | CPS spikes: {m.cps_spike_count} (max {m.cps_max:.2f})",
        f"Warmth step max: {d.max_warmth_step:.3f} | Anchor range: {d.anchor_range:.3f}",
        f"Speak: {d.speak_counts}",
    ]
    if m.notes:
        lines.append(f"Notes: {', '.join(m.notes)}")
    failed = [c for c in m.behavior_contracts if not c.passed]
    if failed:
        lines.append("Contract failures:")
        for c in failed:
            lines.append(f"  [{c.turn_index}] {c.tag}: {c.violation}")
    lines.append("--- turns ---")
    for t in report.session.turns:
        preview = (t.text or "(silent)")[:60]
        lines.append(f"  {t.index:2d} [{t.speak.value:8s}] w={t.effective_warmth:.2f} cps={t.cps_score:.1f} | {preview}")
    if report.failure:
        lines.append("")
        lines.append(report.failure.debug_trace)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    raw_argv = argv or sys.argv[1:]
    use_openai = "--openai" in raw_argv or os.environ.get("SMOKE_USE_OPENAI", "") == "1"
    compare = "--compare" in raw_argv
    json_out = "--json" in raw_argv
    record = "--record" in raw_argv or os.environ.get("PERSONA_RECORD_RUNS", "") == "1"
    observe = "--observe" in raw_argv or os.environ.get("PERSONA_OBSERVE", "") == "1"
    argv = [a for a in raw_argv if a not in ("--json", "--record", "--observe", "--compare", "--openai")]
    script = argv[0] if argv else "semantic_chaos"

    if script not in ADVERSARIAL_SCRIPTS:
        print(f"Unknown script: {script}. Available: {list(ADVERSARIAL_SCRIPTS)}", file=sys.stderr)
        return 1

    if compare:
        if not os.environ.get("OPENAI_API_KEY"):
            print("OPENAI_API_KEY required for --compare", file=sys.stderr)
            return 1
        if not os.environ.get("GEMINI_API_KEY"):
            print("GEMINI_API_KEY required for --compare", file=sys.stderr)
            return 1
        cmp = compare_gemini_vs_openai(script)
        if json_out:
            print(json.dumps({
                "script": cmp.script_name,
                "grade_parity": cmp.grade_parity,
                "contract_parity": cmp.contract_parity,
                "anchor_delta": cmp.anchor_delta,
                "gemini_grade": cmp.gemini.smoke.grade,
                "openai_grade": cmp.openai.smoke.grade,
            }, indent=2))
        else:
            print(format_report(cmp.gemini))
            print()
            print(format_report(cmp.openai))
            print(f"\nParity: grade={cmp.grade_parity} contract={cmp.contract_parity} anchor_Δ={cmp.anchor_delta:.3f}")
        return 0 if cmp.grade_parity else 1

    adapter = get_adapter("openai") if use_openai else default_adapter()
    if use_openai and not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set", file=sys.stderr)
        return 1
    if not use_openai and not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set", file=sys.stderr)
        return 1

    report = run_smoke(script, adapter, record=record, observe=observe)
    if json_out:
        print(json.dumps({
            "script": report.script_name,
            "adapter": report.adapter,
            "grade": report.smoke.grade,
            "contract_pass_rate": report.smoke.contract_pass_rate,
            "cps_spike_count": report.smoke.cps_spike_count,
            "drift_grade": report.smoke.drift.grade,
            "readiness_score": report.failure.readiness_score if report.failure else None,
            "readiness_grade": report.failure.readiness_grade if report.failure else None,
            "primary_weakness": report.failure.primary_weakness if report.failure else None,
        }, indent=2))
    else:
        print(format_report(report))
    return 0 if report.smoke.grade in ("A", "B") else 1


if __name__ == "__main__":
    raise SystemExit(main())
