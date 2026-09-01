"""Logat Papua urban (Melayu Papua) — korpus multi-sumber, sa/ko."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_PAPUA_DIALECT_ALIASES = frozenset({"papua", "papuan", "logat_papua", "papua_id"})

_DATA_PATH = Path(__file__).parent / "data" / "papua_dialect_hf_samples.json"

_PHRASE_SKIP_KEYS = frozenset({"hf_melayu_papua_health_raw"})

# Kategori terlalu partikel-heavy — tidak dimasukkan ke prompt suara (tetap di korpus)
_PROMPT_PHRASE_SKIP_CATEGORIES = frozenset({
    "particles_kah_iyo",
    "particles_eee",
    "hf_melayu_papua_health",
    "regional_jayapura",
    "regional_merauke",
    "regional_manokwari",
})

_FORBIDDEN_BY_REGION: dict[str, tuple[str, ...]] = {
    "Maluku / Ambon (bukan Papua!)": ("beta", "katong", "par", "ose"),
    "Jakarta / Betawi": ("gue", "gw", "lu", "elu", "bro"),
    "Makassar / Bugis": ("ki", "ta", "mi", "nu", "ji", "kio", "tania", "maki"),
    "Medan / Batak": ("pe", "gan", "kaban", "horas", "mang", "boi", "hata", "podang"),
}

_RULE_LINES = [
    "Nuansa logat: Melayu Papua urban — sobat dekat Jayapura yang nongkrong & cerita, BUKAN customer service.",
    "Dasar: sa/ko (bukan saya/kamu), pu (sa pu cerita), tra/su/mo — campur natural dengan Indonesia.",
    "PENTING: beta = Ambon/Maluku (BUKAN Papua). dong/dorang = mereka.",
    "Buka respons dengan eee/adooo/mari su/siooo kalau pas — hangat seperti teman duduk bareng.",
    "Partikel kah/iyo/toh/eee: sesekali saja — jangan tiap kalimat, jangan berlebihan.",
    "Prioritas: obrolan hidup & peduli dulu; nuansa Papua sebagai bumbu — bukan teater logat.",
    "JANGAN campur logat daerah lain (beta, ki/ta, pe/horas, gue/lu).",
]

_PROMPT_PHRASE_LIMIT = 18
_VOCAB_PROMPT_LIMIT = 14


@lru_cache(maxsize=1)
def _load_samples() -> dict:
    if not _DATA_PATH.is_file():
        return {}
    try:
        return json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def is_papua_dialect(dialect: str | None) -> bool:
    if not dialect:
        return False
    return dialect.strip().lower().replace("-", "_") in _PAPUA_DIALECT_ALIASES


def forbidden_dialect_lines() -> list[str]:
    lines = ["Hindari logat lain:"]
    for region, words in list(_FORBIDDEN_BY_REGION.items())[:3]:
        sample = ", ".join(f"'{w}'" for w in words[:4])
        lines.append(f"- {region.split('(')[0].strip()}: {sample}")
    return lines


def grammar_summary_lines() -> list[str]:
    return [
        "Inti tata bahasa (gaya berbicara Papua — seling ringan):",
        "- Singkat: sa/ko/pi/tra/su/mo/skali — lafal & intonasi khas, jangan dipaksakan tiap kata",
        "- Milik: subjek dulu + pu terpisah — sa pu rumah, ko pu maitua (bukan rumahku/istrimu)",
        "- Urutan: subjek dulu, predikat sesudah; kebanyakan predikat sama seperti Indonesia baku",
        "- Su menggantikan -lah perintah: Makan sudah…, Tidur sudah… (su terpisah, tidak menempel ke kerja)",
        "- E/eee menggantikan 'yah': kas tau sa eee; mo/toh/kah/bar penegas & pelengkap",
    ]


def speaking_style_prompt_lines() -> list[str]:
    """Panduan gaya berbicara Papua — dari korpus dialek resmi."""
    data = _load_samples()
    ref = data.get("grammar_reference", {})
    style = ref.get("speaking_style") if isinstance(ref, dict) else None
    guide = data.get("speaking_style_guide")
    lines = ["Gaya berbicara / dialek Papua (ko harus paham):"]
    if isinstance(style, dict):
        summary = style.get("summary")
        if summary:
            lines.append(f"- {summary}")
        shortened = style.get("shortened_words")
        if shortened:
            lines.append(f"- Singkatan umum: {shortened}")
        for key in (
            "possession_rule",
            "word_order",
            "su_instead_of_lah",
            "e_instead_of_yah",
            "mo_emphasis",
            "toh_emphasis",
            "kah_complement",
            "baru_emphasis",
        ):
            note = style.get(key)
            if note:
                lines.append(f"- {note}")
    if isinstance(guide, dict):
        lines.append("- Contoh pasangan (nuansa — jangan dibaca persis):")
        shown = 0
        for block_key in (
            "possession_examples",
            "su_lah_examples",
            "mo_emphasis_examples",
            "toh_emphasis_examples",
            "kah_complement_examples",
        ):
            items = guide.get(block_key)
            if not isinstance(items, list):
                continue
            for item in items[:1]:
                text = str(item).strip()
                if text:
                    lines.append(f"  · {text}")
                    shown += 1
                if shown >= 5:
                    break
            if shown >= 5:
                break
    return lines


def kah_iyo_prompt_lines() -> list[str]:
    return [
        "Partikel opsional (pakai secukupnya, ~1 dari 3-4 kalimat):",
        "- Tanya: akhiri kah — Ko pernah ke sana kah?, Ko mo pi kah?, Ko su makan kah?",
        "- JANGAN tanya pakai ...ko... di akhir. Ke sana = dua kata terpisah.",
        "- Konfirmasi: Iyo toh. / Oke tu.",
        "- Heran: Macam apa eee… (jarang). / Mamayo (jarang).",
        "- Bujukan: Ko jemput sa eee?, Kas tau sa eee.",
    ]


def _merged_vocabulary() -> dict[str, str]:
    data = _load_samples()
    merged: dict[str, str] = {}
    for key in ("vocabulary_core", "vocabulary_warungfiksi", "vocabulary_popular"):
        block = data.get(key)
        if isinstance(block, dict):
            merged.update(block)
    return merged


def popular_vocab_prompt_lines() -> list[str]:
    """Kata populer Papua — dari korpus user & urban."""
    popular = _load_samples().get("vocabulary_popular")
    if not isinstance(popular, dict) or not popular:
        return []
    lines = ["Kata populer Papua (arti — ko harus paham & seling natural):"]
    order = (
        "sa", "ko", "tong", "kam", "trapapa", "tramau",
        "stecu", "yombex", "yap_sene", "epen_kah_cupen_toh",
    )
    for key in order:
        if key in popular:
            lines.append(f"- {key.replace('_', ' ')}: {popular[key]}")
    return lines


def vocabulary_prompt_lines() -> list[str]:
    vocab = _merged_vocabulary()
    if not vocab:
        return []
    # Kosakata paling sering & aman untuk obrolan ringan
    prefer = (
        "sa", "ko", "tong", "kam", "de", "pu", "tra", "trapapa", "tramau", "su", "mo",
        "stecu", "yombex", "yap_sene", "epen", "mangarti", "trapapa", "iyo", "bagitu",
        "mamayo", "bale", "pi", "lai", "tu", "eee", "bar",
    )
    lines = ["Kosakata inti (seling natural, jangan dipaksakan):"]
    shown = 0
    for key in prefer:
        if key in vocab and shown < _VOCAB_PROMPT_LIMIT:
            lines.append(f"- {key}: {vocab[key]}")
            shown += 1
    return lines


def papua_language_prompt() -> str:
    return (
        "Bahasa Indonesia natural + nuansa Melayu Papua ringan: sa/ko, pu, tra/su/mo. "
        "Kah/iyo/eee sesekali (eee = e panjang di akhir). Beta = Ambon (salah). Jangan ki/ta, pe/horas, gue/lu."
    )


def _companion_voice_persona() -> dict:
    data = _load_samples()
    block = data.get("companion_voice_persona")
    return block if isinstance(block, dict) else {}


def companion_persona_prompt_lines() -> list[str]:
    """Persona sobat Jayapura — nongkrong, Mop, peduli ko."""
    persona = _companion_voice_persona()
    if not persona:
        return []
    lines = [f"Persona suara: {persona.get('role', 'Sobat dekat Jayapura')}."]
    vibe = persona.get("vibe")
    if vibe:
        lines.append(f"- Suasana: {vibe}")
    for item in persona.get("speak_like") or []:
        text = str(item).strip()
        if text:
            lines.append(f"- {text}")
    openings = persona.get("opening_examples") or []
    if openings:
        lines.append("- Contoh sapaan pembuka (variati, boleh panjang & peduli):")
        for ex in openings[:3]:
            lines.append(f"  · {ex}")
    pattern_lines = opening_pattern_lines()
    if pattern_lines:
        lines.extend(pattern_lines)
    caring = persona.get("caring_topics") or []
    if caring:
        lines.append("- Peduli ko (seling natural, jangan setiap turn):")
        for topic in caring[:3]:
            lines.append(f"  · {topic}")
    offers = persona.get("conversation_offers") or []
    if offers:
        lines.append("- Tawarin topik obrolan (max 1x per beberapa menit):")
        for offer in offers[:2]:
            lines.append(f"  · {offer}")
    return lines


def slang_barge_in_responses() -> list[dict]:
    data = _load_samples()
    items = data.get("slang_barge_in_responses")
    base: list[dict] = []
    if isinstance(items, list):
        base = [item for item in items if isinstance(item, dict)]
    try:
        from persona_ai.personality.papua_gaul_jalanan import slang_barge_in_entries

        extra = slang_barge_in_entries()
        if extra:
            return base + extra
    except ImportError:
        pass
    return base


def slang_barge_in_prompt_lines() -> list[str]:
    """Template respon cepat saat user lempar slang gaul (full duplex)."""
    items = slang_barge_in_responses()
    if not items:
        return []
    lines = [
        "Slang gaul full-duplex — kalau ko potong dengan frasa ini, balas CEPAT (1-2 kalimat):",
    ]
    for item in items[:10]:
        triggers = item.get("user_triggers")
        response = str(item.get("response", "")).strip()
        if not response:
            continue
        trigger_text = ", ".join(str(t) for t in triggers[:3]) if isinstance(triggers, list) else "?"
        lines.append(f"  · Ko bilang ({trigger_text}) -> {response}")
    return lines


def full_duplex_prompt_lines() -> list[str]:
    """Respon natural saat ko potong bicara (barge-in / interupsi)."""
    acks = ack_templates_papua()
    lines = [
        "Full duplex — ko boleh potong sa kapan saja:",
        "- Sa HARUS stop bicara, dengar ko, balas singkat — jangan lanjut monolog.",
        "- Respon interupsi natural: Siooo iyo iyo / Ah masa? / Betul kah? / Eee iyo toh.",
    ]
    for phrase in (acks.get("interruption") or [])[:4]:
        lines.append(f"  · {phrase}")
    for phrase in (acks.get("humor") or [])[:3]:
        lines.append(f"  · (Mop/humor) {phrase}")
    lines.extend(slang_barge_in_prompt_lines())
    return lines


def papua_friend_lines() -> list[str]:
    return [
        "Peranmu: sobat dekat dari Jayapura — nongkrong, cerita, baku Mop. Bukan asisten layanan.",
        "Bicara hangat: eee/adooo/mari su/siooo di awal kalau pas; sa/ko + pu/tra/su/mo seling natural.",
        "Peduli ko: ingatkan istirahat/makan kalau ko cape atau sibuk — jangan paksa diri.",
        "Cerita & tanggapi dulu — jangan wawancara ko dengan pertanyaan demi pertanyaan.",
        "Ko potong sa? Stop, dengar, balas singkat (Siooo iyo iyo / Betul kah?) — full duplex natural.",
        "Ko lempar Mop? Tangkis ringan (Adooo… / Ih…) — baru balas Mop ko kalau mau, tra perlu ketawa teater.",
        "Setelah jawab, berhenti dengar — biar ko lanjut kalau mau.",
    ]


def papua_steer_reminder() -> str:
    return (
        "Sobat Jayapura: sa/ko, pu, tra/su, eee/adooo/mari su. Tanya pakai kah di akhir kalau perlu. "
        "Ko potong? Stop & dengar (Siooo iyo iyo). Mop? Tangkis Hahaha iyo ka? Jangan beta/ki/ta/pe/gue. "
        "Jawab langsung, hangat — bukan asisten. Sesekali tawarin Mop/topik santai — jangan spam."
    )


def opening_greeting_canonical() -> str:
    persona = _companion_voice_persona()
    canonical = persona.get("opening_canonical")
    return str(canonical).strip() if canonical else ""


def opening_pattern_lines() -> list[str]:
    persona = _companion_voice_persona()
    pattern = persona.get("opening_pattern")
    if not isinstance(pattern, list) or not pattern:
        return []
    lines = ["Pola sapaan pembuka (boleh panjang & peduli — variasi, jangan robot copy-paste):"]
    for step in pattern:
        text = str(step).strip()
        if text:
            lines.append(f"- {text}")
    canonical = opening_greeting_canonical()
    if canonical:
        lines.append(f"- Contoh panjang (variati kalimat, jangan baca persis): {canonical[:280]}…")
    return lines


def papua_opening_greeting_prompt(display_name: str) -> str:
    name = display_name or "Papua AI"
    canonical = opening_greeting_canonical()
    persona = _companion_voice_persona()
    examples = persona.get("opening_examples") or []
    short_ex = str(examples[0]) if examples else f"Adooo pace, ko apa kabar dulu kah?"
    canonical_hint = (
        f"Contoh gaya panjang (variati, jangan copy persis): {canonical[:320]}…"
        if canonical
        else f"Contoh: {short_ex}"
    )
    return (
        f"[call connected] Ko sobat dekat dari Jayapura — suka nongkrong sambil cerita. "
        f"Sapa ko hangat sebagai {name} (beberapa kalimat pendek, nuansa Papua: sa/ko, adooo/eee/mantap eee/mari su). "
        "BOLEH panjang & peduli seperti teman: tanya kabar, ingatkan jangan paksa diri/tra tidur-tidur, "
        "tanya sudah makan papeda, ajak pi makan dulu kalau belum — baru lanjut cerita. "
        f"{canonical_hint} "
        "Jangan beta, ki, ta, pe, gue. Lalu diam dengar ko."
    )


def _flatten_phrases(raw: object, *, parent_key: str = "") -> list[str]:
    phrases: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            text = str(item).strip()
            if not text or len(text) > 120:
                continue
            if text not in phrases:
                phrases.append(text)
    elif isinstance(raw, dict):
        for key, items in raw.items():
            if key in _PHRASE_SKIP_KEYS:
                continue
            for text in _flatten_phrases(items, parent_key=key):
                if text not in phrases:
                    phrases.append(text)
    return phrases


def _prompt_phrase_samples() -> list[str]:
    data = _load_samples()
    block = data.get("papua_phrases")
    if not isinstance(block, dict):
        return all_example_phrases()[:_PROMPT_PHRASE_LIMIT]
    phrases: list[str] = []
    for key, items in block.items():
        if key in _PROMPT_PHRASE_SKIP_CATEGORIES or not isinstance(items, list):
            continue
        for text in items:
            t = str(text).strip()
            if t and len(t) <= 90 and t not in phrases:
                phrases.append(t)
            if len(phrases) >= _PROMPT_PHRASE_LIMIT:
                return phrases
    return phrases


def all_example_phrases() -> list[str]:
    data = _load_samples()
    return _flatten_phrases(data.get("papua_phrases"))


def phrase_count() -> int:
    return len(all_example_phrases())


def ack_templates_papua() -> dict[str, list[str]]:
    data = _load_samples()
    block = data.get("companion_ack_papua")
    if isinstance(block, dict):
        return {k: list(v) for k, v in block.items() if isinstance(v, list)}
    return {}


def dialect_prompt_lines(dialect: str | None, *, language: str = "id") -> list[str]:
    if not is_papua_dialect(dialect) or language != "id":
        return []
    lines = list(_RULE_LINES)
    lines.extend(companion_persona_prompt_lines())
    lines.extend(full_duplex_prompt_lines())
    lines.extend(grammar_summary_lines())
    lines.extend(speaking_style_prompt_lines())
    lines.extend(kah_iyo_prompt_lines())
    lines.extend(popular_vocab_prompt_lines())
    lines.extend(vocabulary_prompt_lines())
    lines.extend(forbidden_dialect_lines())
    samples = _prompt_phrase_samples()
    if samples:
        total = phrase_count()
        lines.append(
            f"Contoh nuansa obrolan ({len(samples)}/{total} — variasi ringan, jangan dibaca persis):"
        )
        lines.extend(f"- {p}" for p in samples)
    return lines
