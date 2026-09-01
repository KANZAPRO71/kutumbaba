"""Regression delta dashboard tests."""

import json

from persona_ai.diagnostics.failure_fingerprint import (
    FingerprintRegistry,
    FingerprintRegistryEntry,
    FingerprintReport,
    FingerprintedFailure,
    FailureFingerprint,
)
from persona_ai.diagnostics.failure_taxonomy import FailureReport
from persona_ai.diagnostics.regression_dashboard import (
    RunHistoryStore,
    compute_derived_metrics,
    compute_lifecycle,
    format_dashboard,
    record_smoke_run,
)
from tests.support.stub_llm import StubLLMAdapter
from persona_ai.sim.drift_harness import DriftMetrics, SessionReport
from persona_ai.sim.smoke_openai import SmokeMetrics, SmokeReport, run_smoke


def _fp_id(suffix: str = "abc12345") -> str:
    return f"fp_{suffix}"


def _fake_fp(fp_id: str, ctx: str = "instructional_intent") -> FailureFingerprint:
    return FailureFingerprint(
        fingerprint_id=fp_id,
        semantic_key=f"FP::BDV_UNDER_RESPONSIVE::{ctx.upper()}::INTENT_RESOLUTION",
        display=f"bdv_under_responsive|root=interpret.intent_resolution|ctx={ctx}|mismatch=ACK_ONLY->RESPOND",
        failure_class="bdv_under_responsive",
        root_cause="interpret.intent_resolution",
        context_signature=ctx,
        mismatch="ACK_ONLY->RESPOND",
        normalized=f"bdv_under_responsive|root=interpret.intent_resolution|ctx={ctx}|mismatch=ACK_ONLY->RESPOND",
    )


def _smoke_with_fps(fp_ids: list[str], script: str = "sarcasm_stack") -> SmokeReport:
    items = []
    for fp_id in fp_ids:
        fp = _fake_fp(fp_id)
        items.append(FingerprintedFailure(failure=None, fingerprint=fp))  # type: ignore[arg-type]
    fp_report = FingerprintReport(
        items=items,
        unique_ids=fp_ids,
        by_fingerprint={i: 1 for i in fp_ids},
    )
    failure = FailureReport(
        events=[],
        by_domain={},
        by_class={},
        by_severity={},
        structural_count=len(fp_ids),
        degraded_count=0,
        benign_count=0,
        readiness_score=93.0 if fp_ids else 100.0,
        readiness_grade="v2_ready",
        fingerprints=fp_report,
    )
    metrics = DriftMetrics(
        turn_count=8,
        warmth_values=[0.6] * 8,
        anchor_values=[0.6] * 8,
        max_warmth_step=0.05,
        warmth_range=0.08,
        anchor_range=0.06,
        warmth_std=0.02,
        speak_counts={"RESPOND": 4, "ACK_ONLY": 4},
        max_same_speak_streak=2,
        silence_ratio=0.1,
        mechanical_score=0.1,
        identity_stable=True,
        grade="A",
    )
    smoke = SmokeMetrics(
        drift=metrics,
        cps_spike_count=0,
        cps_max=0.0,
        cps_turns=[],
        behavior_contracts=[],
        contract_pass_rate=0.875 if fp_ids else 1.0,
        llm_turns=4,
        word_overflow_count=0,
        silence_correct=0,
        silence_expected=0,
        grade="B" if fp_ids else "A",
    )
    return SmokeReport(
        script_name=script,
        adapter="stub",
        session=SessionReport(script_name=script, turns=[], metrics=metrics),
        smoke=smoke,
        failure=failure,
    )


class TestLifecycle:
    def test_new_on_first_sighting(self, tmp_path):
        reg = FingerprintRegistry(tmp_path / "reg.json")
        lc = compute_lifecycle([_fp_id()], previous_present=None, registry=reg)
        assert lc.new == [_fp_id()]
        assert lc.known == []
        assert lc.closed == []
        assert lc.regressions == []

    def test_known_on_second_sighting(self, tmp_path):
        reg = FingerprintRegistry(tmp_path / "reg.json")
        reg.entries[_fp_id()] = FingerprintRegistryEntry(
            fingerprint_id=_fp_id(),
            display="x",
            semantic_key="y",
            first_seen_at="t",
            last_seen_at="t",
            occurrence_count=1,
        )
        lc = compute_lifecycle([_fp_id()], previous_present=[_fp_id()], registry=reg)
        assert lc.new == []
        assert lc.known == [_fp_id()]

    def test_closed_when_absent_from_run(self, tmp_path):
        reg = FingerprintRegistry(tmp_path / "reg.json")
        lc = compute_lifecycle([], previous_present=[_fp_id("aaa"), _fp_id("bbb")], registry=reg)
        assert set(lc.closed) == {_fp_id("aaa"), _fp_id("bbb")}

    def test_regression_when_closed_reappears(self, tmp_path):
        reg = FingerprintRegistry(tmp_path / "reg.json")
        reg.entries[_fp_id()] = FingerprintRegistryEntry(
            fingerprint_id=_fp_id(),
            display="x",
            semantic_key="y",
            first_seen_at="t",
            last_seen_at="t",
            status="closed",
        )
        lc = compute_lifecycle([_fp_id()], previous_present=[], registry=reg)
        assert lc.regressions == [_fp_id()]


class TestDerivedMetrics:
    def test_clean_run_high_stability(self):
        lc = compute_lifecycle([], previous_present=[_fp_id()], registry=FingerprintRegistry())
        m = compute_derived_metrics(lc)
        assert m.stability_index == 1.0
        assert m.fix_effectiveness == 1.0

    def test_regression_lowers_stability(self, tmp_path):
        reg = FingerprintRegistry(tmp_path / "r.json")
        reg.entries[_fp_id()] = FingerprintRegistryEntry(
            fingerprint_id=_fp_id(),
            display="",
            semantic_key="",
            first_seen_at="",
            last_seen_at="",
            status="closed",
        )
        lc = compute_lifecycle([_fp_id()], previous_present=[], registry=reg)
        m = compute_derived_metrics(lc)
        assert m.stability_index < 1.0


class TestRecordAndDashboard:
    def test_two_run_improvement_delta(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        hist_path = tmp_path / "history.json"
        reg = FingerprintRegistry(reg_path)
        hist = RunHistoryStore(hist_path)

        r1 = _smoke_with_fps([_fp_id()])
        record_smoke_run(r1, run_id="run-1", registry=reg, history=hist, persist=True)

        r2 = _smoke_with_fps([])
        r2.smoke.contract_pass_rate = 1.0
        r2.smoke.grade = "A"
        r2.failure.readiness_score = 100.0
        record_smoke_run(r2, run_id="run-2", registry=reg, history=hist, persist=True)

        out = format_dashboard(hist, reg, script_name="sarcasm_stack")
        assert "RUN DELTA" in out
        assert "closed: 1" in out
        assert "regressions: 0" in out
        assert reg.entries[_fp_id()].status == "closed"

    def test_regression_detected_on_third_run(self, tmp_path):
        reg_path = tmp_path / "reg.json"
        hist_path = tmp_path / "history.json"
        reg = FingerprintRegistry(reg_path)
        hist = RunHistoryStore(hist_path)

        record_smoke_run(_smoke_with_fps([_fp_id()]), run_id="run-1", registry=reg, history=hist, persist=True)
        record_smoke_run(_smoke_with_fps([]), run_id="run-2", registry=reg, history=hist, persist=True)
        record_smoke_run(_smoke_with_fps([_fp_id()]), run_id="run-3", registry=reg, history=hist, persist=True)

        out = format_dashboard(hist, reg, script_name="sarcasm_stack")
        assert "REGRESSION:" in out
        assert _fp_id() in out

    def test_smoke_record_integration(self, tmp_path, monkeypatch):
        reg_path = tmp_path / "reg.json"
        hist_path = tmp_path / "history.json"

        def _record(report, **kw):
            return record_smoke_run(
                report,
                run_id=kw.get("run_id", "test"),
                registry=FingerprintRegistry(reg_path),
                history=RunHistoryStore(hist_path),
                persist=True,
            )

        monkeypatch.setattr(
            "persona_ai.diagnostics.regression_dashboard.record_smoke_run",
            _record,
        )
        run_smoke("semantic_chaos", StubLLMAdapter(), record=True)
        assert hist_path.exists()
        assert len(json.loads(hist_path.read_text())["runs"]) == 1
