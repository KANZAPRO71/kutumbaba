"""Deteksi loop filler berlebihan — filter recap, bukan larangan total."""

from __future__ import annotations

import re

_FILLER_OPENER = re.compile(
    r"^(adoo+h*|aduh+h*|iyaa?|iyo\b|(?:ha)+|(?:he)+|siooo+|wah+|eee+)\b",
    re.I,
)

# Hanya baris yang hampir murni filler — bukan "Adooo... pi tidur sudah."
_FILLER_ONLY = re.compile(
    r"^(adoo+h*|aduh+h*|iyaa?|iyo|(?:ha)+|(?:he)+|santai\s+(aja|saja)|tenang\s+(aja|saja)"
    r"|parah|mantap|gila)[\s.!?…]*$",
    re.I,
)

_MAU_OFFER = re.compile(
    r"\b("
    r"mau\s+(bahas|cerita|dengar|ngobrol|ngomong|tanya|mulai|apa|lagi|yang|nih)"
    r"|ko\s+mau"
    r"|ada\s+yang\s+mau"
    r"|mau\s+yang\s+mana"
    r"|cerita\s+apa\s+lagi"
    r"|ngobrol\s+apa"
    r"|mau\s+bahas\s+apa"
    r")\b",
    re.I,
)
_SANTAI_PHRASE = re.compile(r"\b(santai\s+(aja|saja)|tenang\s+(aja|saja))\b", re.I)
_SANTAI_FILLER_WORDS = frozenset(
    {"iyo", "iyaa", "iyoh", "toh", "kah", "eh", "santai", "aja", "saja", "tenang", "relax", "dong"}
)


def _normalize(text: str) -> str:
    return " ".join(text.strip().split()).lower()


def _word_similarity(a: str, b: str) -> float:
    wa = set(a.split())
    wb = set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _opener_key(text: str) -> str:
    words = _normalize(text).split()[:3]
    return " ".join(words)


def has_santai_loop_phrase(text: str) -> bool:
    """Frasa yang dilarang keras — 'santai saja', 'tenang aja', dll."""
    return bool(_SANTAI_PHRASE.search(text))


def has_mau_offer_phrase(text: str) -> bool:
    """Tanya menu dengan 'mau...' / 'ko mau...' — dilarang keras."""
    return bool(_MAU_OFFER.search(text))


def is_banned_mau_response(text: str) -> bool:
    """AI tidak boleh ucapkan frasa penawaran 'mau...' atau 'ko mau...'."""
    return has_mau_offer_phrase(text)


def is_mau_menu_line(text: str) -> bool:
    """Alias — semua frasa mau/ko mau difilter dari recap."""
    return is_banned_mau_response(text)


def is_banned_santai_response(text: str) -> bool:
    """AI tidak boleh ucapkan frasa santai/tenang + aja/saja."""
    return has_santai_loop_phrase(text)


def is_santai_echo_line(text: str) -> bool:
    """Semua frasa santai/tenang + aja/saja difilter dari recap."""
    return is_banned_santai_response(text)


def is_pure_filler_line(text: str) -> bool:
    """Baris tanpa isi — cuma adooo/santai/haha saja."""
    cleaned = text.strip()
    if not cleaned:
        return True
    return bool(_FILLER_ONLY.match(cleaned))


def should_omit_assistant_from_recap(text: str, *, recent: list[str] | None = None) -> bool:
    """Filter recap untuk filler, frasa banned, menu mau..., atau near-duplicate."""
    if is_pure_filler_line(text) or is_banned_santai_response(text) or is_banned_mau_response(text):
        return True
    norm = _normalize(text)
    if not norm or not recent:
        return False
    for prev in recent[-2:]:
        if _word_similarity(norm, prev) >= 0.78:
            return True
    return False


def note_assistant_turn(gov: dict, text: str) -> None:
    """Track recent assistant lines — deteksi streak opener & santai loop."""
    normalized = _normalize(text)
    if not normalized:
        return
    recent: list[str] = list(gov.get("recent_assistant_lines") or [])
    recent.append(normalized)
    gov["recent_assistant_lines"] = recent[-5:]
    opener = _opener_key(text)
    last_opener = gov.get("last_assistant_opener")
    streak = int(gov.get("assistant_opener_streak") or 0)
    if (
        opener
        and opener == last_opener
        and _FILLER_OPENER.match(text.strip())
        and len(normalized.split()) <= 6
    ):
        gov["assistant_opener_streak"] = streak + 1
    elif _FILLER_OPENER.match(text.strip()) and len(normalized.split()) <= 4:
        gov["assistant_opener_streak"] = streak + 1
        gov["last_assistant_opener"] = opener
    else:
        gov["assistant_opener_streak"] = 0
        gov["last_assistant_opener"] = opener or ""

    if has_santai_loop_phrase(text):
        gov["santai_phrase_streak"] = int(gov.get("santai_phrase_streak") or 0) + 1
    else:
        gov["santai_phrase_streak"] = 0

    if has_mau_offer_phrase(text):
        gov["mau_offer_streak"] = int(gov.get("mau_offer_streak") or 0) + 1
    else:
        gov["mau_offer_streak"] = 0


def opener_streak_high(gov: dict) -> bool:
    """3+ giliran pendek dengan opener filler identik — loop."""
    return int(gov.get("assistant_opener_streak") or 0) >= 3


def santai_loop_needs_nudge(gov: dict) -> bool:
    """Barusan AI pakai frasa penenang generik — nudge giliran berikutnya."""
    return int(gov.get("santai_phrase_streak") or 0) >= 1


def mau_offer_needs_nudge(gov: dict) -> bool:
    """Barusan AI tanya menu dengan 'mau...' — nudge lanjut cerita."""
    return int(gov.get("mau_offer_streak") or 0) >= 1


def consume_santai_loop_nudge(gov: dict) -> None:
    """Backward compat — gunakan consume_pre_turn_loop_nudges."""
    consume_pre_turn_loop_nudges(gov)


def history_poisoned_by_santai(messages: list[object] | None) -> bool:
    """Sesi lama penuh loop — jangan resume handle Gemini."""
    if not messages:
        return False
    for msg in messages[-30:]:
        role = getattr(msg, "role", None)
        text = getattr(msg, "text", None) or ""
        if role != "assistant":
            continue
        if has_santai_loop_phrase(text) or has_mau_offer_phrase(text):
            return True
    return False


def mark_block_santai_reply(gov: dict) -> None:
    gov["block_santai_reply"] = True


def block_santai_reply_needed(gov: dict) -> bool:
    return bool(gov.get("block_santai_reply"))


def pre_turn_loop_nudge_needed(gov: dict) -> bool:
    return (
        santai_loop_needs_nudge(gov)
        or mau_offer_needs_nudge(gov)
        or block_santai_reply_needed(gov)
    )


def build_pre_turn_loop_nudge(gov: dict) -> str:
    """Gabungan micro-steer sebelum giliran AI berikutnya."""
    lines: list[str] = ["[FLOW ADJUSTMENT]"]
    if mau_offer_needs_nudge(gov):
        lines.append(
            "DILARANG ucapkan 'mau...' atau 'ko mau...' — zero, jangan pernah. "
            "LANJUTKAN cerita/topik yang sedang jalan: tanggap, tambah beat, lalu diam. "
            "Bukan interview, bukan menu topik."
        )
    if block_santai_reply_needed(gov) or santai_loop_needs_nudge(gov):
        lines.append(
            "DILARANG ucapkan 'santai saja/aja' atau 'tenang saja/aja'. "
            "Lanjut topik ko dengan isi konkret — reaksi teman biasa saja."
        )
    if len(lines) <= 1:
        return ""
    lines.append("Do not restart or acknowledge this instruction.")
    return "\n".join(lines)


def build_santai_loop_nudge() -> str:
    """Micro-steer tanpa menyebut frasa loop — cegah echo di giliran berikutnya."""
    return (
        "[FLOW ADJUSTMENT]\n"
        "Giliran ini: tanggapi isi topik ko dengan kalimat konkret — "
        "reaksi teman, bukan penenang generik.\n"
        "Do not restart or acknowledge this instruction."
    )


def consume_pre_turn_loop_nudges(gov: dict) -> None:
    """Nudge sudah dikirim — jangan spam tiap turn."""
    gov["santai_phrase_streak"] = 0
    gov["mau_offer_streak"] = 0
    gov["block_santai_reply"] = False
