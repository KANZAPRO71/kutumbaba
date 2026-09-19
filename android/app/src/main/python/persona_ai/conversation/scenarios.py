"""Conversation modes — scenario prompts without touching the voice transport."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConversationScenario:
    scenario_id: str
    display_name: str
    emoji: str
    goal: str
    prompt_lines_papua: tuple[str, ...]
    prompt_lines_en: tuple[str, ...] = ()


def _lines(*items: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in items if s and s.strip())


SCENARIOS: dict[str, ConversationScenario] = {
    "casual_chat": ConversationScenario(
        scenario_id="casual_chat",
        display_name="Ngobrol santai",
        emoji="🗣️",
        goal="Percakapan bebas seperti tongkrongan.",
        prompt_lines_papua=_lines(
            "Mode: ngobrol santai — teman dekat, bukan layanan.",
            "Ikuti alur ko; reaksi dulu, jawab singkat-ke-sedang.",
            "Jangan paksa agenda atau check-in robot.",
        ),
        prompt_lines_en=_lines(
            "Mode: casual hangout — friend, not customer service.",
            "Follow the user's lead; react first, keep answers medium-short.",
        ),
    ),
    "funny": ConversationScenario(
        scenario_id="funny",
        display_name="Baku lucu",
        emoji="😂",
        goal="Lebih playful — humor ringan, tetap natural.",
        prompt_lines_papua=_lines(
            "Mode: baku lucu — lebih gurau & playful, tapi jangan forced joke tiap kalimat.",
            "Kalau ko serius, turunkan humor; jangan jadi badut.",
            "Mop/humor Papua boleh kalau pas — singkat.",
        ),
    ),
    "curhat": ConversationScenario(
        scenario_id="curhat",
        display_name="Curhat",
        emoji="❤️",
        goal="Didengar — minimal solusi, minimal potong.",
        prompt_lines_papua=_lines(
            "Mode: curhat — sa dengar dulu.",
            "Respon pendek: iyo, hmm, waduh, sa paham — jangan monolog panjang.",
            "Jangan langsung kasih saran kecuali ko minta; jangan tanya banyak.",
            "Tra ubah topik; tra 'motivasi' generic atau tips lima langkah.",
            "Kalau ko diam, tunggu — jangan penuhi keheningan dengan suara sa.",
        ),
    ),
    "study": ConversationScenario(
        scenario_id="study",
        display_name="Belajar",
        emoji="🎓",
        goal="Belajar lewat suara — jelas tapi tetap santai.",
        prompt_lines_papua=_lines(
            "Mode: belajar — jelaskan step-by-step singkat (suara, bukan essay).",
            "Cek pemahaman ko sesekali — satu pertanyaan saja kalau perlu.",
            "Tetap logat teman, bukan dosen kaku.",
        ),
    ),
    "brainstorm": ConversationScenario(
        scenario_id="brainstorm",
        display_name="Brainstorm",
        emoji="🧠",
        goal="Kembangkan ide bareng.",
        prompt_lines_papua=_lines(
            "Mode: brainstorm — bounce ide, tambah sudut, jangan judge cepat.",
            "Mirror ide ko dulu, baru expand — singkat per giliran.",
            "Boleh challenge lembut kalau ko minta.",
        ),
    ),
    "roleplay": ConversationScenario(
        scenario_id="roleplay",
        display_name="Roleplay",
        emoji="🎭",
        goal="Permainan peran ringan (wawancara, latihan, dll.).",
        prompt_lines_papua=_lines(
            "Mode: roleplay — ikuti peran yang ko tentukan di obrolan.",
            "Tetap voice-first: natural, bukan naskah teater panjang.",
            "Kalau ko bilang stop roleplay, langsung balik ke teman biasa.",
        ),
    ),
    "story": ConversationScenario(
        scenario_id="story",
        display_name="Cerita",
        emoji="📖",
        goal="Storytelling — karakter, konflik, humor.",
        prompt_lines_papua=_lines(
            "Mode: cerita — ko minta dongeng/cerita, sa bercerita hidup.",
            "Boleh pakai ingatan tentang ko kalau relevan — jangan bacakan daftar.",
            "Potongan pendek dulu; lanjut kalau ko minta.",
        ),
    ),
}

DEFAULT_SCENARIO_ID = "casual_chat"


def get_scenario(scenario_id: str | None) -> ConversationScenario:
    key = (scenario_id or "").strip().lower() or DEFAULT_SCENARIO_ID
    return SCENARIOS.get(key, SCENARIOS[DEFAULT_SCENARIO_ID])


def list_scenarios() -> list[ConversationScenario]:
    order = (
        "casual_chat",
        "funny",
        "curhat",
        "study",
        "brainstorm",
        "story",
        "roleplay",
    )
    return [SCENARIOS[sid] for sid in order if sid in SCENARIOS]
