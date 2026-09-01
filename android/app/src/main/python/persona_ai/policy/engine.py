"""Policy engine v1 — pre_check + post_check hard gates only."""

from __future__ import annotations

import re

from persona_ai.core.types import BehaviorDirectiveVector, PolicySignal, SpeakAction, VoiceDirective
from persona_ai.llm.adapter import LLMAdapter
from persona_ai.policy.rules import (
    CRISIS_RESOURCE_LINE,
    DEFAULT_CRISIS_KEYWORDS,
    DEFAULT_INPUT_BLOCK_FALLBACK,
    DEFAULT_OUTPUT_BLOCK_FALLBACK,
    FP1_AI_DISCLAIMER,
    FP3_CREDENTIAL_COLLECT,
    FP4_DEFAULT_DENYLIST,
    INPUT_BLOCK_PATTERNS,
    OUTPUT_BLOCK_PATTERNS,
)
from persona_ai.policy.types import (
    PiiHandling,
    PolicyConstraints,
    PolicyContext,
    PolicyPreCheckResult,
    PolicyResult,
    PolicyStatus,
    PolicyViolation,
    SensitiveDepth,
)

_PII_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PII_PHONE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\d{8,15}\b")


class PolicyEngine:
    """Hard gate — answers 'boleh keluar?' not 'AI harus bagaimana?'."""

    def __init__(self, context: PolicyContext | None = None) -> None:
        self._context = context or PolicyContext(
            crisis_keywords=list(DEFAULT_CRISIS_KEYWORDS),
            phrase_denylist=list(FP4_DEFAULT_DENYLIST),
        )

    @property
    def context(self) -> PolicyContext:
        return self._context

    def pre_check(self, user_text: str) -> PolicyPreCheckResult:
        """Input gate — runs before Behavior. Does not use BDV."""
        text = user_text.strip()
        lower = text.lower()
        tier0: list[PolicySignal] = []
        inject_lines: list[str] = []
        blocked_topics: list[str] = []
        pii_handling = self._context.pii_mode
        max_depth = SensitiveDepth.STANDARD

        for keyword in self._context.crisis_keywords:
            if keyword.lower() in lower:
                tier0.append(
                    PolicySignal(
                        type="must_respond",
                        reason="safety",
                    )
                )
                inject_lines.append(CRISIS_RESOURCE_LINE)
                break

        if self._context.regulated_domain and self._context.required_disclaimer:
            inject_lines.append(self._context.required_disclaimer)

        input_blocked = False
        block_reason: str | None = None

        for rule_id, pattern, reason in INPUT_BLOCK_PATTERNS:
            if pattern.search(text):
                input_blocked = True
                block_reason = reason
                blocked_topics.append(rule_id)
                break

        if (
            not input_blocked
            and self._context.pii_mode == PiiHandling.REFUSE
            and (_PII_EMAIL.search(text) or _PII_PHONE.search(text))
        ):
            input_blocked = True
            block_reason = "Blocked: sensitive PII in input"
            pii_handling = PiiHandling.REFUSE
            max_depth = SensitiveDepth.NONE

        constraints = PolicyConstraints(
            required_disclaimer=self._context.required_disclaimer,
            blocked_topics=blocked_topics,
            blocked_phrases=list(self._context.phrase_denylist),
            pii_handling=pii_handling,
            max_sensitive_depth=max_depth,
            inject_system_lines=inject_lines,
            tier0_signals=tier0,
            input_blocked=input_blocked,
            block_reason=block_reason,
            fallback_text=DEFAULT_INPUT_BLOCK_FALLBACK if input_blocked else None,
        )

        return PolicyPreCheckResult(
            constraints=constraints,
            tier0_signals=tier0,
            input_blocked=input_blocked,
            block_reason=block_reason,
            fallback_text=constraints.fallback_text,
        )

    def post_check(
        self,
        draft: str | None,
        constraints: PolicyConstraints,
        voice: VoiceDirective,
        *,
        user_text: str = "",
        bdv: BehaviorDirectiveVector | None = None,
    ) -> PolicyResult:
        """Output gate — binary match on hard categories."""
        if draft is None or not draft.strip():
            return PolicyResult(status=PolicyStatus.APPROVED, final_text=draft)

        text = draft.strip()
        violations: list[PolicyViolation] = []

        for rule_id, pattern, detail in OUTPUT_BLOCK_PATTERNS:
            if pattern.search(text):
                violations.append(PolicyViolation(rule_id=rule_id, category="safety", detail=detail))

        if FP3_CREDENTIAL_COLLECT.search(text):
            violations.append(
                PolicyViolation(rule_id="FP3", category="credentials", detail="Credential collection")
            )

        for slur in self._context.slur_denylist:
            if slur and slur.lower() in text.lower():
                violations.append(
                    PolicyViolation(rule_id="FP2", category="hate", detail="Slur/hate match")
                )
                break

        rewrite_violations: list[PolicyViolation] = []

        if FP1_AI_DISCLAIMER.search(text):
            rewrite_violations.append(
                PolicyViolation(rule_id="FP1", category="chatbot", detail="AI disclaimer phrase")
            )

        for phrase in constraints.blocked_phrases:
            if phrase.lower() in text.lower():
                rewrite_violations.append(
                    PolicyViolation(rule_id="FP4", category="denylist", detail=f"Phrase: {phrase}")
                )

        if any(v.category == "safety" or v.rule_id == "FP3" or v.category == "hate" for v in violations):
            return PolicyResult(
                status=PolicyStatus.BLOCK,
                violations=violations + rewrite_violations,
                final_text=self._block_fallback(user_text, bdv, voice),
            )

        if rewrite_violations:
            return PolicyResult(
                status=PolicyStatus.REWRITE,
                violations=rewrite_violations,
                rewrite_hint="Remove policy-violating phrases; preserve voice register.",
                preserve_voice_register=True,
                final_text=text,
            )

        return PolicyResult(status=PolicyStatus.APPROVED, final_text=text)

    def apply_post_check(
        self,
        draft: str,
        constraints: PolicyConstraints,
        voice: VoiceDirective,
        adapter: LLMAdapter | None,
        *,
        user_text: str = "",
        bdv: BehaviorDirectiveVector | None = None,
    ) -> tuple[str | None, PolicyResult]:
        """Post-check with max 1 rewrite — local first, optional LLM rewrite."""
        result = self.post_check(draft, constraints, voice, user_text=user_text, bdv=bdv)
        if result.status == PolicyStatus.APPROVED:
            return result.final_text, result
        if result.status == PolicyStatus.BLOCK:
            return result.final_text, result

        rewritten = apply_local_rewrite(draft, result)
        recheck = self.post_check(rewritten, constraints, voice, user_text=user_text, bdv=bdv)
        if recheck.status == PolicyStatus.APPROVED:
            recheck.rewrite_count = 1
            return recheck.final_text, recheck

        if adapter is not None and recheck.status == PolicyStatus.REWRITE:
            llm_rewrite = rewrite_via_llm(
                adapter,
                original=rewritten,
                voice=voice,
                hint=recheck.rewrite_hint or "",
                user_message=user_text,
            )
            if llm_rewrite:
                final_check = self.post_check(
                    llm_rewrite, constraints, voice, user_text=user_text, bdv=bdv
                )
                final_check.rewrite_count = 1
                if final_check.status == PolicyStatus.APPROVED:
                    return final_check.final_text, final_check
                if final_check.status == PolicyStatus.BLOCK:
                    return final_check.final_text, final_check

        blocked = PolicyResult(
            status=PolicyStatus.BLOCK,
            violations=result.violations,
            final_text=self._block_fallback(user_text, bdv, voice),
            rewrite_count=1,
        )
        return blocked.final_text, blocked

    def _block_fallback(
        self,
        user_text: str,
        bdv: BehaviorDirectiveVector | None,
        voice: VoiceDirective,
    ) -> str:
        if bdv and bdv.speak == SpeakAction.RESPOND:
            return DEFAULT_OUTPUT_BLOCK_FALLBACK
        return DEFAULT_OUTPUT_BLOCK_FALLBACK


def apply_local_rewrite(text: str, result: PolicyResult) -> str:
    cleaned = FP1_AI_DISCLAIMER.sub("", text).strip()
    for violation in result.violations:
        if violation.rule_id == "FP4":
            phrase = violation.detail.removeprefix("Phrase: ")
            cleaned = re.sub(re.escape(phrase), "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned or text


def rewrite_via_llm(
    adapter: LLMAdapter,
    *,
    original: str,
    voice: VoiceDirective,
    hint: str,
    user_message: str,
) -> str | None:
    from persona_ai.core.types import LLMRequest, Message

    rewrite_voice = voice.model_copy(
        update={
            "prompt_fragments": list(voice.prompt_fragments)
            + [
                "Rewrite the draft below to fix policy violations.",
                f"Hint: {hint}",
                "Preserve warmth and word limit. Output only the rewritten reply.",
                f"Draft: {original}",
            ],
        }
    )
    req = LLMRequest(user_message=user_message or "Rewrite.", voice=rewrite_voice, history=[])
    try:
        return adapter.complete(req).text.strip() or None
    except Exception:
        return None
