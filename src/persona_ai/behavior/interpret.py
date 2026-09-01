"""Intent interpretation heuristics — v0 rules."""

from __future__ import annotations

import re

from persona_ai.core.types import IntentDepth, IntentInterpretation, Message

VENT_KEYWORDS = (
    "capek",
    "lelah",
    "stres",
    "stress",
    "sedih",
    "kesal",
    "marah",
    "frustra",
    "berat",
    "tough",
    "tired",
    "exhausted",
    "gapapa",
)

CLOSURE_ACKS = {"oke", "ok", "thanks", "thank you", "siap", "noted", "got it"}

TRAILING_DEFER = ("jadi", "terus", "nah", "hmm", "hm")
TRAILING_HESITATION = ("sebenarnya", "actually", "honestly")
CONTINUATION_KEYWORDS = ("lanjut", "lanjutkan", "teruskan", "continue", "go on")
CONFUSION_KEYWORDS = ("bingung", "confused", "gimana ya", "tidak yakin", "masih ragu")
MIXED_PIVOT = ("tapi", "but", "sebenarnya", "actually")
QUESTION_HINTS = ("gimana", "how", "apa", "why", "kenapa", "kapan", "when", "?")
GREETING_WORDS = frozenset(
    {"halo", "hai", "hi", "hey", "hello", "helo", "hallo", "pagi", "siang", "sore", "malam"}
)
GREETING_PHRASES = frozenset(
    {
        "selamat pagi",
        "selamat siang",
        "selamat sore",
        "selamat malam",
        "halo halo",
        "hai hai",
    }
)
INDIRECT_INSTRUCTION_VERBS = (
    "explain",
    "jelasin",
    "jelaskan",
    "clarify",
    "describe",
    "properly",
    "tell me",
    "walk me through",
    "help me understand",
    "break down",
)
INDIRECT_INSTRUCTION_PIVOTS = ("wait", "actually", "—", " - ", "jangan", "don't", "dont")

# Word-boundary match — avoids false positives like "apa" inside "gapapa"
_QUESTION_SHAPE_RE = re.compile(
    r"\?(?:\s|$)|\b(gimana|how|apa|why|kenapa|kapan|when)\b",
    re.IGNORECASE,
)


def _ends_with_ellipsis(text: str) -> bool:
    t = text.rstrip()
    return t.endswith("...") or t.endswith("…")


def _has_question_shape(text: str) -> bool:
    return bool(_QUESTION_SHAPE_RE.search(text))


def _normalize_intent_text(text: str) -> str:
    cleaned = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    return " ".join(cleaned.lower().split())


def is_social_greeting(text: str) -> bool:
    cleaned = _normalize_intent_text(text)
    if not cleaned:
        return False
    if cleaned in GREETING_PHRASES or cleaned in GREETING_WORDS:
        return True
    words = cleaned.split()
    return words[0] in {"halo", "hai", "hi", "hey", "hello", "helo", "hallo"} and len(words) <= 4


def _is_standalone_continuation(text: str) -> bool:
    cleaned = re.sub(r"[.!?…]+$", "", text.strip().lower()).strip()
    return cleaned in {
        "lanjut",
        "lanjutkan",
        "teruskan",
        "continue",
        "go on",
        "lanjutkan lagi",
    }


def interpret(message: Message, last_assistant_word_count: int) -> IntentInterpretation:
    text = message.text.strip().lower()
    words = text.split()
    reason_codes: list[str] = []

    has_vent_kw = any(k in text for k in VENT_KEYWORDS)
    is_direct_question = _has_question_shape(text) and not text.startswith(("tolong", "please"))
    is_command = text.startswith(("tolong", "please", "bantu", "help"))
    is_confusion = any(k in text for k in CONFUSION_KEYWORDS)
    is_continuation = _is_standalone_continuation(text) or (
        any(k in text for k in CONTINUATION_KEYWORDS) and len(words) >= 2
    )
    if is_continuation:
        reason_codes.append("continuation_request")
    has_pivot = any(p in text for p in MIXED_PIVOT)

    is_closure = text in CLOSURE_ACKS and last_assistant_word_count >= 40
    if is_closure:
        reason_codes.append("closure_ack")

    # Dismissive frustration ("yaudah gapapa lah") — not pure closure
    is_frustrated_dismissal = ("yaudah" in text or "ya udah" in text) and has_vent_kw and len(words) >= 2

    is_mixed = has_vent_kw and (is_direct_question or is_confusion or (has_pivot and _has_question_shape(text)))
    if is_mixed:
        reason_codes.append("mixed_intent")

    is_vent = has_vent_kw and not is_mixed and not is_direct_question and not is_confusion
    is_rhetorical = is_vent and _ends_with_ellipsis(text)

    has_instruction_verb = any(v in text for v in INDIRECT_INSTRUCTION_VERBS)
    has_instruction_pivot = any(p in text for p in INDIRECT_INSTRUCTION_PIVOTS)
    is_indirect_instruction = (
        has_instruction_verb
        and has_instruction_pivot
        and not is_direct_question
        and not is_command
        and not is_closure
    )
    if is_indirect_instruction:
        reason_codes.append("indirect_instruction_chain")

    incompleteness = 0.0
    if _ends_with_ellipsis(text):
        if is_continuation:
            reason_codes.append("continuation_request")
        elif is_vent or is_rhetorical:
            reason_codes.append("rhetorical_vent")
        elif not is_mixed:
            incompleteness = 0.8
            reason_codes.append("incomplete_utterance")
    elif any(text.rstrip().endswith(t) for t in TRAILING_DEFER):
        incompleteness = 0.8
        reason_codes.append("incomplete_utterance")
    elif (
        any(h in text for h in TRAILING_HESITATION)
        and any(text.rstrip().endswith(h) for h in TRAILING_HESITATION)
        and not is_vent
        and not is_mixed
    ):
        incompleteness = 0.8
        reason_codes.append("trailing_hesitation")

    emotional_load = 0.2
    if has_vent_kw or is_frustrated_dismissal:
        emotional_load = 0.65
        reason_codes.append("user_venting")
    if is_confusion:
        emotional_load = min(1.0, emotional_load + 0.1)
        reason_codes.append("confusion_signal")
    if "!" in message.text:
        emotional_load = min(1.0, emotional_load + 0.15)

    depth = IntentDepth.SHALLOW
    intent_need = 0.25
    requires_response = False

    if is_closure:
        depth = IntentDepth.NONE
        intent_need = 0.0
    elif is_mixed or is_confusion:
        depth = IntentDepth.MODERATE
        intent_need = 0.65
        requires_response = True
        reason_codes.append("mixed_or_confusion_priority")
    elif is_direct_question or is_command:
        depth = IntentDepth.MODERATE if is_direct_question else IntentDepth.DEEP
        intent_need = 0.6 if is_direct_question else 0.9
        requires_response = True
        reason_codes.append("direct_question" if is_direct_question else "command")
    elif is_social_greeting(text):
        depth = IntentDepth.SHALLOW
        intent_need = 0.55
        requires_response = True
        reason_codes.append("social_greeting")
    elif is_continuation:
        depth = IntentDepth.SHALLOW
        intent_need = 0.7
        requires_response = True
    elif has_instruction_verb and not is_closure:
        depth = IntentDepth.MODERATE
        intent_need = 0.7
        requires_response = True
        reason_codes.append("instruction_request")
    elif is_indirect_instruction:
        depth = IntentDepth.MODERATE
        intent_need = 0.65
        requires_response = True
    elif is_frustrated_dismissal:
        depth = IntentDepth.SHALLOW
        intent_need = 0.2
        requires_response = False
        reason_codes.append("frustrated_dismissal")
    elif len(words) <= 2 and text in CLOSURE_ACKS | {"hmm", "iya", "ya", "oh"}:
        depth = IntentDepth.NONE
        intent_need = 0.0
        reason_codes.append("ack_or_backchannel")
    elif is_vent:
        depth = IntentDepth.SHALLOW
        intent_need = 0.25
        requires_response = False
    elif incompleteness >= 0.5:
        depth = IntentDepth.NONE
        intent_need = 0.0

    return IntentInterpretation(
        depth=depth,
        intent_need=intent_need,
        requires_response=requires_response,
        is_direct_question=is_direct_question,
        is_command=is_command,
        is_vent=is_vent,
        is_closure_ack=is_closure,
        is_rhetorical=is_rhetorical,
        is_mixed_intent=is_mixed,
        is_confusion_signal=is_confusion,
        incompleteness_score=incompleteness,
        emotional_load=emotional_load,
        reason_codes=reason_codes,
    )
