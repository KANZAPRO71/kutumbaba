"""Voice-call anti-chatbot — patterns & prompts (bukan mode chat teks)."""

from __future__ import annotations

import re

from persona_ai.personality.papua_dialect_phrases import is_papua_dialect

# Pola yang kedengaran robot di panggilan suara (bukan hanya closing FAQ).
VOICE_CHATBOT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\btentu saja\b", re.I), "VO1"),
    (re.compile(r"\bbaik,?\s*(saya|aku)\b", re.I), "VO2"),
    (re.compile(r"\bsaya (mengerti|paham|dengar)\b", re.I), "VO3"),
    (re.compile(r"\biyaa?,?\s*paham\b", re.I), "VO4"),
    (re.compile(r"\boke noted\b", re.I), "VO5"),
    (re.compile(r"\bsemoga (membantu|bermanfaat)\b", re.I), "VO6"),
    (re.compile(r"\bsaya di sini untuk membantu\b", re.I), "VO7"),
    (re.compile(r"\bada yang mau ditanyakan", re.I), "VO8"),
    (re.compile(r"\bada lagi yang (bisa|mau)", re.I), "VO9"),
    (re.compile(r"\bmau bahas apa (lagi|nih)\b", re.I), "VO10"),
    (re.compile(r"\bmau bahas apa\b", re.I), "VO10b"),
    (re.compile(r"\b(soal|tentang) .{0,40}(atau)\b", re.I), "VO10c"),
    (re.compile(r"\bmau (dengar|cerita) mop\b", re.I), "VO10d"),
    (re.compile(r"\bsa siap (dengar|membantu|mendengar|hibur)\b", re.I), "VO7b"),
    (re.compile(r"\bsa kasih masukan\b", re.I), "VO7c"),
    (re.compile(r"\bkasian sekali\b", re.I), "VO7d"),
    (re.compile(r"\bbagaimana,? soh agak mendingan\b", re.I), "VO7e"),
    (re.compile(r"\bmau mulai dari mana\b", re.I), "VO9b"),
    (re.compile(r"\bbutuh bantuan\b", re.I), "VO11"),
    (re.compile(r"\bhow can i help\b", re.I), "VO12"),
    (re.compile(r"\banything else\b", re.I), "VO13"),
    (re.compile(r"\bsebagai (ai|asisten|assistant)\b", re.I), "VO14"),
    (re.compile(r"\bberikut (penjelasan|informasi|ringkasan)\b", re.I), "VO15"),
    (re.compile(r"\bpertama\b.*\bkedua\b", re.I | re.S), "VO16"),
    (re.compile(r"\bsaya (paham|mengerti) perasaan\b", re.I), "VO17"),
    (re.compile(r"\bperasaan ko\b", re.I), "VO18"),
    (re.compile(r"\bwajar (ko|kamu) (merasa|rasakan)\b", re.I), "VO19"),
    (re.compile(r"\b(mode konselor|sebagai pendengar setia)\b", re.I), "VO20"),
]

# Live voice turns should stay spoken-short; long blocks = text-mode habit.
VOICE_ARTICLE_WORD_THRESHOLD = 75


def score_voice_chatbot_slip(text: str) -> tuple[float, list[str]]:
    """Return 0–1 slip score + hit codes for assistant speech on a live call."""
    if not text or not text.strip():
        return 0.0, []
    hits: list[str] = []
    score = 0.0
    for pattern, code in VOICE_CHATBOT_PATTERNS:
        if pattern.search(text):
            hits.append(code)
            score += 0.35
    if len(text.split()) >= VOICE_ARTICLE_WORD_THRESHOLD:
        hits.append("VA1")
        score += 0.45
    return min(1.0, score), hits


def natural_slip_nudge_text(
    hits: list[str],
    *,
    dialect: str | None = None,
) -> str:
    """One-line whisper after chatbot slip — shapes the next turn only, never spoken aloud."""
    if not hits:
        return ""
    papua = is_papua_dialect(dialect)
    if "VA1" in hits:
        if papua:
            return (
                "(Catatan internal — jangan ucapkan: barusan terlalu panjang seperti artikel. "
                "Giliran depan: ~2–4 kalimat lisan sa/ko, lalu diam.)"
            )
        return (
            "(Internal note — do not speak aloud: last reply was too long like an article. "
            "Next turn: ~2–4 spoken sentences, then listen.)"
        )
    counselor = bool(set(hits) & {"VO17", "VO18", "VO19", "VO20"})
    if counselor:
        if papua:
            return (
                "(Catatan internal — jangan ucapkan: barusan mirip konselor/CS. "
                "Giliran depan: teman tongkrongan sa/ko — tanggapi singkat, bukan validasi panjang.)"
            )
        return (
            "(Internal note — do not speak aloud: last reply sounded like a counselor. "
            "Next turn: casual friend tone, brief reaction — not long validation.)"
        )
    if papua:
        return (
            "(Catatan internal — jangan ucapkan: barusan mirip asisten CS. "
            "Giliran depan: jawab langsung sa/ko, tanpa 'Tentu saja'/'Saya dengar' "
            "atau tanya 'ada lagi'.)"
        )
    return (
        "(Internal note — do not speak aloud: last reply sounded like a CS bot. "
        "Next turn: answer directly as a friend, no 'Of course' or check-in closers.)"
    )


def natural_persona_refresh_text(*, dialect: str | None = None) -> str:
    """Mid-call persona anchor — Gemini Live drifts toward Q&A/counselor after several minutes."""
    papua = is_papua_dialect(dialect)
    if papua:
        return (
            "(Catatan internal — jangan ucapkan: tetap sobat Jayapura tongkrongan, "
            "bukan konselor/CS. Jawab singkat sa/ko, dengar ko — jangan tanya balik.)"
        )
    return (
        "(Internal note — do not speak aloud: stay a casual hangout friend, "
        "not counselor or FAQ bot. Short turns, then listen.)"
    )


def voice_not_chat_prompt_lines(
    dialect: str | None = None,
    *,
    language: str = "id",
) -> list[str]:
    """Explicit voice-vs-chat examples for Gemini Live S2S."""
    papua = is_papua_dialect(dialect) and language == "id"
    if papua:
        return [
            "Suara hidup ≠ chat teks (wajib):",
            "- Ini panggilan tongkrongan — BUKAN WhatsApp panjang atau artikel.",
            "- SALAH (robot): 'Tentu saja! Saya dengar ko… Berikut penjelasan saya…'",
            "- BENAR (teman): 'Adoo iyo toh — menurut sa begini ee…' lalu diam.",
            "- SALAH: 'Iyaa paham. Ada yang mau ditanyakan lagi?'",
            "- BENAR: 'Iyo ka, mantap.' — stop, biar ko lanjut.",
            "- Jangan baca daftar 1-2-3; jangan 'Pertama… Kedua…'; max ~2–4 kalimat singkat.",
            "- Kalau perlu panjang (cerita Mop), tetap gaya cerita lisan — bukan esai.",
        ]
    return [
        "Live voice ≠ text chat (mandatory):",
        "- This is a phone hangout — NOT a long WhatsApp reply or article.",
        "- WRONG: 'Of course! I hear you… Here is my explanation…'",
        "- RIGHT: 'Yeah totally — I'd say…' then stop and listen.",
        "- WRONG: 'Got it. Anything else I can help with?'",
        "- RIGHT: 'Fair enough.' — then silence.",
        "- No numbered lists or 'First… Second…'; ~2–4 short spoken sentences.",
    ]
