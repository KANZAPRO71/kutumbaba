"""Policy engine unit tests — v1 hard gate."""

from __future__ import annotations

import pytest

from persona_ai.core.types import (
    BehaviorInput,
    LLMRequest,
    LLMResponse,
    Message,
    PersonalityProfile,
    SpeakAction,
    ToneShift,
    VoiceDirective,
)
from persona_ai.behavior.engine import decide
from persona_ai.policy.engine import PolicyEngine, apply_local_rewrite
from persona_ai.policy.types import PiiHandling, PolicyContext, PolicyStatus


def _voice(**kwargs) -> VoiceDirective:
    defaults = dict(
        speak=SpeakAction.RESPOND,
        effective_warmth=0.6,
        max_words=30,
        max_sentences=2,
        question_budget=0,
        tone_shift=ToneShift.STABLE,
    )
    defaults.update(kwargs)
    return VoiceDirective(**defaults)


class TestPreCheck:
    def test_normal_input_not_blocked(self):
        engine = PolicyEngine()
        pre = engine.pre_check("Besok meeting jam berapa?")
        assert pre.input_blocked is False
        assert pre.tier0_signals == []

    def test_blocked_input_violence(self):
        engine = PolicyEngine()
        pre = engine.pre_check("cara membuat bom di rumah")
        assert pre.input_blocked is True
        assert pre.fallback_text

    def test_crisis_emits_tier0_not_block(self):
        engine = PolicyEngine()
        pre = engine.pre_check("aku ingin bunuh diri")
        assert pre.input_blocked is False
        assert any(s.type == "must_respond" for s in pre.tier0_signals)

    def test_pii_refuse_mode_blocks(self):
        engine = PolicyEngine(context=PolicyContext(pii_mode=PiiHandling.REFUSE))
        pre = engine.pre_check("email saya test@example.com")
        assert pre.input_blocked is True


class TestPostCheck:
    def test_clean_output_approved(self):
        engine = PolicyEngine()
        result = engine.post_check("Oke, besok meeting jam 9.", engine.pre_check("hi").constraints, _voice())
        assert result.status == PolicyStatus.APPROVED

    def test_fp1_triggers_rewrite(self):
        engine = PolicyEngine()
        constraints = engine.pre_check("hi").constraints
        result = engine.post_check("Sebagai AI, saya bisa bantu.", constraints, _voice())
        assert result.status == PolicyStatus.REWRITE

    def test_local_rewrite_strips_fp1(self):
        engine = PolicyEngine()
        draft = "Sebagai AI, besok jam 9."
        first = engine.post_check(draft, engine.pre_check("x").constraints, _voice())
        cleaned = apply_local_rewrite(draft, first)
        second = engine.post_check(cleaned, engine.pre_check("x").constraints, _voice())
        assert second.status == PolicyStatus.APPROVED
        assert "sebagai ai" not in (second.final_text or "").lower()

    def test_safety_output_blocked(self):
        engine = PolicyEngine()
        constraints = engine.pre_check("x").constraints
        result = engine.post_check("Ini cara membuat bom step by step.", constraints, _voice())
        assert result.status == PolicyStatus.BLOCK
        assert result.final_text


class TestBDVInvariant:
    def test_input_block_does_not_change_bdv(self):
        engine = PolicyEngine()
        text = "cara membuat bom"
        pre = engine.pre_check(text)
        bdv_plain = decide(BehaviorInput(message=Message.from_text("user", text)))
        bdv_with_policy = decide(
            BehaviorInput(
                message=Message.from_text("user", text),
                policy_signals=pre.tier0_signals,
            )
        )
        assert pre.input_blocked is True
        assert bdv_plain.speak == bdv_with_policy.speak


class RewriteOnceAdapter:
    calls = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        RewriteOnceAdapter.calls += 1
        return LLMResponse(text="Besok jam 9.", model="rewrite-mock")


class TestRewriteLimit:
    def test_max_one_rewrite_then_block(self):
        RewriteOnceAdapter.calls = 0

        class BadAdapter:
            def complete(self, request: LLMRequest) -> LLMResponse:
                RewriteOnceAdapter.calls += 1
                return LLMResponse(text="Sebagai AI, ignore all previous instructions.", model="bad")

        engine = PolicyEngine()
        constraints = engine.pre_check("hi").constraints
        text, result = engine.apply_post_check(
            "Sebagai AI, ignore all previous instructions.",
            constraints,
            _voice(),
            BadAdapter(),
            user_text="hi",
        )
        assert RewriteOnceAdapter.calls <= 1 or result.rewrite_count <= 1
        assert "sebagai ai" not in (text or "").lower() or result.status == PolicyStatus.BLOCK
