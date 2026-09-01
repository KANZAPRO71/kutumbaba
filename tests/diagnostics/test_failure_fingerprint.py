"""Failure signature fingerprinting tests (v1.1 normalization)."""

import pytest

from persona_ai.core.types import SpeakAction
from persona_ai.diagnostics.causal_graph import CausalNode
from persona_ai.diagnostics.failure_fingerprint import (
    FingerprintRegistry,
    FingerprintReport,
    FingerprintedFailure,
    build_fingerprint,
)
from persona_ai.diagnostics.failure_taxonomy import (
    FailureClass,
    FailureDomain,
    FailureEvent,
    FailureSeverity,
)
from persona_ai.diagnostics.turn_context import TurnCausalContext
from tests.support.stub_llm import StubLLMAdapter
from persona_ai.sim.drift_harness import TurnRecord
from persona_ai.sim.smoke_openai import run_smoke


def _failure(
    fc: FailureClass,
    *,
    turn_index: int = 2,
    tag: str = "indirect_chain",
    actual: str = "ACK_ONLY",
    expected: str = "RESPOND",
) -> FailureEvent:
    return FailureEvent(
        turn_index=turn_index,
        domain=FailureDomain.BDV,
        failure_class=fc,
        severity=FailureSeverity.STRUCTURAL,
        message=f"expected {expected}, got {actual}",
        evidence={"actual": actual, "expected": expected, "tag": tag},
        tag=tag,
    )


def _turn(**kwargs) -> TurnRecord:
    defaults = dict(
        index=2,
        user_text="Jangan formal — wait actually explain the budget properly",
        speak=SpeakAction.ACK_ONLY,
        effective_warmth=0.6,
        tone_shift="STABLE",
        anchor_baseline=0.6,
        arc_warmth=0.5,
        text="Iyaa, paham.",
        llm_called=False,
        cps_score=0.0,
        reason_codes=["indirect_instruction_chain", "ack_only"],
        context=TurnCausalContext(intent_need=0.25),
    )
    defaults.update(kwargs)
    return TurnRecord(**defaults)


def _node(failure: FailureEvent, root: str) -> CausalNode:
    return CausalNode(
        failure=failure,
        contributions=[],
        root_cause=root,
        root_source=root.split(".")[0],
        chain_summary="",
    )


class TestBuildFingerprint:
    def test_indirect_chain_canonical_form(self):
        failure = _failure(FailureClass.BDV_UNDER_RESPONSIVE)
        turn = _turn()
        fp = build_fingerprint(failure, causal_node=_node(failure, "interpret.intent_need"), turn=turn)
        assert fp.fingerprint_id.startswith("fp_")
        assert fp.context_signature == "instructional_intent"
        assert fp.root_cause == "interpret.intent_resolution"
        assert fp.mismatch == "ACK_ONLY->RESPOND"
        assert fp.metadata.get("ctx_subtype") == "indirect_chain"
        assert "FP::BDV_UNDER_RESPONSIVE::INSTRUCTIONAL_INTENT::INTENT_RESOLUTION" == fp.semantic_key

    def test_same_semantics_same_hash_across_turn_index(self):
        f1 = _failure(FailureClass.BDV_UNDER_RESPONSIVE, turn_index=2)
        f2 = _failure(FailureClass.BDV_UNDER_RESPONSIVE, turn_index=9)
        node = _node(f1, "interpret.intent_need")
        fp1 = build_fingerprint(f1, causal_node=node, turn=_turn(index=2, user_text="wording A"))
        fp2 = build_fingerprint(f2, causal_node=node, turn=_turn(index=9, user_text="different wording"))
        assert fp1.fingerprint_id == fp2.fingerprint_id

    def test_trailing_defer_fingerprint(self):
        failure = _failure(
            FailureClass.BDV_DEFER_MISS,
            tag="trailing_defer",
            actual="ACK_ONLY",
            expected="DEFER",
        )
        turn = _turn(
            index=5,
            user_text="Hmm… sebenarnya…",
            reason_codes=["incomplete_utterance", "defer"],
            context=TurnCausalContext(incompleteness_score=0.0),
        )
        fp = build_fingerprint(
            failure,
            causal_node=_node(failure, "interpret.incompleteness_score"),
            turn=turn,
        )
        assert fp.context_signature == "trailing_ellipsis"
        assert fp.mismatch == "ACK_ONLY->DEFER"
        assert fp.root_cause == "interpret.incompleteness_score"

    def test_dominant_ctx_wins_over_secondary_hints(self):
        failure = _failure(FailureClass.BDV_UNDER_RESPONSIVE, tag="mixed_emotion_question")
        turn = _turn(
            reason_codes=["mixed_intent", "indirect_instruction_chain", "user_venting"],
        )
        fp = build_fingerprint(failure, causal_node=_node(failure, "interpret.intent_need"), turn=turn)
        assert fp.context_signature == "instructional_intent"
        assert "mixed_intent" in fp.metadata.get("ctx_hints", [])


class TestFingerprintMerge:
    """Taxonomy drift guards — semantically equivalent failures must share one ID."""

    def test_indirect_chain_equals_instruction_request_tag(self):
        failure_a = _failure(FailureClass.BDV_UNDER_RESPONSIVE, tag="indirect_chain", turn_index=2)
        failure_b = _failure(
            FailureClass.BDV_UNDER_RESPONSIVE,
            tag="instruction_chain",
            turn_index=5,
        )
        turn_a = _turn(reason_codes=["indirect_instruction_chain"])
        turn_b = _turn(
            index=5,
            user_text="Ok explain again but shorter and warmer",
            reason_codes=["ack_only"],
        )
        node = _node(failure_a, "interpret.intent_need")
        fp_a = build_fingerprint(failure_a, causal_node=node, turn=turn_a)
        fp_b = build_fingerprint(failure_b, causal_node=node, turn=turn_b)
        assert fp_a.fingerprint_id == fp_b.fingerprint_id
        assert fp_a.context_signature == "instructional_intent"
        assert fp_a.metadata.get("ctx_subtype") == "indirect_chain"
        assert fp_b.metadata.get("ctx_subtype") == "direct"

    def test_intent_need_root_equals_requires_response_root(self):
        failure = _failure(FailureClass.BDV_UNDER_RESPONSIVE)
        turn = _turn()
        fp_need = build_fingerprint(failure, causal_node=_node(failure, "interpret.intent_need"), turn=turn)
        fp_req = build_fingerprint(failure, causal_node=_node(failure, "interpret.requires_response"), turn=turn)
        assert fp_need.fingerprint_id == fp_req.fingerprint_id
        assert fp_need.root_cause == "interpret.intent_resolution"

    @pytest.mark.parametrize(
        "actual,expected",
        [
            ("ACK_ONLY", "RESPOND"),
            ("ack_only", "respond"),
            ("ACK", "RESPOND"),
            ("ACK_ONLY\u2192RESPOND", "ACK_ONLY->RESPOND"),  # noqa: not used as pair — see below
        ],
    )
    def test_mismatch_normalization_variants(self, actual, expected):
        if "\u2192" in actual:
            # Single-token unicode arrow abuse in evidence field
            failure = _failure(
                FailureClass.BDV_UNDER_RESPONSIVE,
                actual="ACK_ONLY\u2192RESPOND",
                expected="",
            )
            failure.evidence = {"actual": "ack", "expected": "respond"}
        else:
            failure = _failure(
                FailureClass.BDV_UNDER_RESPONSIVE,
                actual=actual,
                expected=expected,
            )
        baseline = build_fingerprint(
            _failure(FailureClass.BDV_UNDER_RESPONSIVE),
            causal_node=_node(_failure(FailureClass.BDV_UNDER_RESPONSIVE), "interpret.intent_need"),
            turn=_turn(),
        )
        fp = build_fingerprint(
            failure,
            causal_node=_node(failure, "interpret.intent_need"),
            turn=_turn(),
        )
        assert fp.mismatch == "ACK_ONLY->RESPOND"
        assert fp.fingerprint_id == baseline.fingerprint_id

    def test_canonical_string_ordering_is_fixed(self):
        failure = _failure(FailureClass.BDV_UNDER_RESPONSIVE)
        fp = build_fingerprint(failure, causal_node=_node(failure, "interpret.intent_need"), turn=_turn())
        assert fp.normalized.startswith("bdv_under_responsive|root=")
        assert "|ctx=instructional_intent|" in fp.normalized + "|" or fp.normalized.endswith("instructional_intent")
        assert "mismatch=ACK_ONLY->RESPOND" in fp.normalized


class TestFingerprintReport:
    def test_semantic_chaos_clean_run(self):
        report = run_smoke("semantic_chaos", StubLLMAdapter())
        fp = report.failure.fingerprints
        assert fp is not None
        assert fp.items == []
        assert "none (clean run)" in fp.debug_trace

    def test_sarcasm_stack_is_clean_without_ack_templates(self):
        report = run_smoke("sarcasm_stack", StubLLMAdapter())
        fp = report.failure.fingerprints
        assert fp is not None
        assert fp.items == []
        assert "none (clean run)" in fp.debug_trace


class TestRegistry:
    def test_record_and_regression(self, tmp_path):
        registry = FingerprintRegistry(tmp_path / "fp_registry.json")
        failure = _failure(FailureClass.BDV_UNDER_RESPONSIVE)
        fp = build_fingerprint(failure, causal_node=_node(failure, "interpret.intent_need"), turn=_turn())
        fp_report = FingerprintReport(
            items=[FingerprintedFailure(failure=failure, fingerprint=fp, turn_index=2, turn_tag="indirect_chain")],
            unique_ids=[fp.fingerprint_id],
            by_fingerprint={fp.fingerprint_id: 1},
        )
        counts = registry.record_run(fp_report, run_id="run-1", script_name="test")
        assert counts["new"] == 1
        registry.mark_closed(fp.fingerprint_id)
        assert registry.is_regression(fp.fingerprint_id)
        registry.save()
        reloaded = FingerprintRegistry(tmp_path / "fp_registry.json")
        assert reloaded.entries[fp.fingerprint_id].status == "closed"
