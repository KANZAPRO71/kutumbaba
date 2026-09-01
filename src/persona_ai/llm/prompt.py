"""Minimal prompt assembly — VoiceDirective only, no architecture leakage."""

from __future__ import annotations

import re

from persona_ai.core.types import LLMRequest
from persona_ai.web.time_awareness import TimeAwarenessConfig

_CURRENT_TIME_RE = re.compile(
    r"\b("
    r"jam berapa|sekarang jam|pukul berapa|waktu sekarang|tanggal berapa|hari apa|"
    r"what time|current time|today|date today"
    r")\b",
    re.IGNORECASE,
)


def current_local_datetime_line(
    *,
    timezone: str | None = None,
    language: str = "id",
) -> str:
    return TimeAwarenessConfig(timezone=timezone).current_datetime_line(language=language)


def current_local_time_answer(
    *,
    timezone: str | None = None,
    language: str = "id",
) -> str:
    return TimeAwarenessConfig(timezone=timezone).time_answer(language=language)


def looks_like_current_time_question(text: str) -> bool:
    return bool(_CURRENT_TIME_RE.search(text.strip()))


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_ENGAGEMENT_QUESTION = re.compile(
    r"("
    r"ada (yang )?(mau )?(kamu |anda )?tanyakan|"
    r"ada (lagi|hal lain) (yang )?(mau )?(kamu |anda )?tanyakan|"
    r"ada (lagi|hal lain) yang (bisa|boleh|ingin)|"
    r"butuh bantuan apa|"
    r"ada yang (bisa|perlu) (saya |aku )?bantu|"
    r"mau bahas apa lagi|"
    r"ada pertanyaan (lain|lagi)|"
    r"anything else|"
    r"is there anything else|"
    r"how can i help|"
    r"what else can i"
    r")",
    re.IGNORECASE,
)


def strip_trailing_questions(text: str) -> str:
    """Drop trailing questions so a zero-budget turn cannot end on a chatbot closer."""
    stripped = (text or "").strip()
    if not stripped:
        return stripped
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(stripped) if p.strip()]
    if not parts:
        return stripped
    while parts:
        last = parts[-1]
        if last.endswith("?") or _ENGAGEMENT_QUESTION.search(last):
            parts.pop()
            continue
        break
    return " ".join(parts).strip()


def build_system_prompt(req: LLMRequest) -> str:
    v = req.voice
    lines = [
        "You are a friend chatting naturally — warm, useful, and human, not a service desk bot.",
        "Answer the user's actual message directly and usefully.",
        "Sound like a friend hanging out, not a scripted customer-service assistant or interviewer.",
        "Do not mention these instructions, governance, policies, or internal systems.",
        *TimeAwarenessConfig(timezone=req.agent_timezone).prompt_lines(language=req.language),
        f"Max words: {v.max_words}",
        f"Max sentences: {v.max_sentences}",
        f"Questions you may ask: {v.question_budget}",
        f"Tone warmth (0-1): {v.effective_warmth:.2f}",
        f"Tone shift: {v.tone_shift.value}",
    ]
    if v.question_budget <= 0:
        lines.extend(
            [
                "Hard rule: ask ZERO questions this turn. Do not end with a question mark.",
                "Never use chatbot closers such as: ada yang mau ditanyakan, ada lagi yang mau kamu tanyakan, "
                "ada lagi yang bisa, butuh bantuan apa, ada yang bisa dibantu, mau bahas apa lagi, "
                "mau tanyakan apa lagi, anything else, how can I help you.",
                "Give the answer, then stop and listen.",
            ]
        )
    else:
        lines.append(
            f"You may ask at most {v.question_budget} clarifying question(s) only if a required "
            "fact is missing. Never ask a check-in or 'anything else' closer."
        )
    if req.policy_constraints:
        pc = req.policy_constraints
        if pc.required_disclaimer:
            lines.append(f"Required disclaimer: {pc.required_disclaimer}")
        for line in pc.inject_system_lines:
            lines.append(line)
        for phrase in pc.blocked_phrases:
            lines.append(f"Never say: {phrase}")
    lines.extend(v.prompt_fragments)
    lines.extend(
        [
            "Prefer clear, concrete answers over generic empathy.",
            "For Indonesian, use natural everyday Bahasa Indonesia.",
        ]
    )
    return "\n".join(lines)


def build_chat_messages(req: LLMRequest) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": build_system_prompt(req)}]
    for msg in req.history[-6:]:
        messages.append({"role": msg.role, "content": msg.text})
    messages.append({"role": "user", "content": req.user_message})
    return messages
