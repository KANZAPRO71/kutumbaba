"""Format conversation mode blocks for Live system instructions."""

from __future__ import annotations

from persona_ai.conversation.experience_modes import scenario_id_for_mode
from persona_ai.conversation.scenarios import ConversationScenario, get_scenario


def scenario_prompt_lines(
    scenario_id: str | None,
    *,
    dialect: str | None = None,
    language: str | None = "id",
) -> list[str]:
    scenario = get_scenario(scenario_id_for_mode(scenario_id))
    papua = dialect and dialect.strip().lower() in {"papua", "papuan", "logat_papua", "papua_id"}
    use_papua = papua and (language or "id") == "id"
    body = scenario.prompt_lines_papua if use_papua else scenario.prompt_lines_en
    if not body and scenario.prompt_lines_papua:
        body = scenario.prompt_lines_papua
    if not body:
        return []
    header = (
        f"MODE OBROLAN: {scenario.display_name} ({scenario.emoji})"
        if use_papua
        else f"CONVERSATION MODE: {scenario.display_name}"
    )
    lines = [header, f"Tujuan: {scenario.goal}"]
    lines.extend(f"- {line}" for line in body)
    return lines


_NATURAL_S2S_EXTRA: dict[str, tuple[str, ...]] = {
    "cerita_tong": (
        "NATURAL VOICE (cerita tong): dengar dulu — reaksi pendek ('hmm', 'terus?').",
        "Jangan solutionizing; jangan monolog; jangan tanya banyak.",
        "Kalau ko pause, diam sebentar — jangan isi dengan suara panjang.",
    ),
    "teman_malam": (
        "NATURAL VOICE (teman malam): tenang, hangat, volume kata sedikit.",
        "Bukan presenter — jangan energi tinggi tiba-tiba.",
    ),
    "teman_jalan": (
        "NATURAL VOICE (teman jalan): ultra singkat — ko mungkin sedang berjalan.",
        "Satu frasa cukup; jangan rangkai pertanyaan.",
    ),
    "nongkrong": (
        "NATURAL VOICE (nongkrong): teman tongkrongan — singkat, ikut alur ko.",
    ),
    "mop": (
        "NATURAL VOICE (mop): timing humor > joke panjang; jangan stand-up monolog.",
    ),
    "curhat": (
        "NATURAL VOICE (curhat): jangan solutionizing — denger dulu.",
        "Satu reaksi singkat per giliran; jangan rangkai saran kecuali ko minta.",
        "Jangan tanya balik kecuali ko bingung dan butuh satu klarifikasi.",
        "Kalau ko pause, diam sebentar — jangan isi dengan ceramah.",
    ),
    "funny": (
        "NATURAL VOICE (lucu): timing lebay > joke panjang; jangan stand-up monolog.",
    ),
    "study": (
        "NATURAL VOICE (belajar): chunk kecil; pause biar ko nyerap.",
    ),
    "brainstorm": (
        "NATURAL VOICE (brainstorm): yes-and ide ko dulu sebelum nambah sudut baru.",
    ),
    "story": (
        "NATURAL VOICE (cerita): potongan hidup per giliran — cliffhanger kecil, bukan essay.",
        "Jangan bacakan daftar ingatan; selip natural kalau relevan.",
    ),
    "roleplay": (
        "NATURAL VOICE (roleplay): tetap di peran; giliran pendek, bukan naskah teater.",
        "Kalau ko bilang stop, langsung balik ke teman biasa.",
    ),
}


def natural_s2s_mode_lines(
    scenario_id: str | None,
    *,
    dialect: str | None = None,
    language: str | None = "id",
) -> list[str]:
    """Extra corset for Gemini natural S2S where Persona BDV is not per-turn."""
    from persona_ai.conversation.experience_modes import normalize_experience_mode
    from persona_ai.conversation.scenarios import DEFAULT_SCENARIO_ID

    mode = normalize_experience_mode(scenario_id) if scenario_id else DEFAULT_SCENARIO_ID
    if mode not in _NATURAL_S2S_EXTRA:
        mode = (scenario_id or DEFAULT_SCENARIO_ID).strip().lower()
    extra = _NATURAL_S2S_EXTRA.get(mode)
    if not extra:
        return []
    papua = dialect and dialect.strip().lower() in {"papua", "papuan", "logat_papua", "papua_id"}
    if papua and (language or "id") == "id":
        return list(extra)
    return [line.replace("NATURAL VOICE", "NATURAL S2S") for line in extra]


def scenario_for_client(scenario: ConversationScenario) -> dict[str, str]:
    return {
        "id": scenario.scenario_id,
        "display_name": scenario.display_name,
        "emoji": scenario.emoji,
        "goal": scenario.goal,
    }


def mid_session_experience_mode_steer(
    mode: str | None,
    *,
    prev_mode: str | None = None,
    dialect: str | None = None,
    language: str | None = "id",
) -> str:
    """Realtime steer text when user switches experience mode mid Live call."""
    from persona_ai.conversation.experience_modes import get_experience_profile, normalize_experience_mode

    key = normalize_experience_mode(mode)
    prev = normalize_experience_mode(prev_mode) if prev_mode else ""
    profile = get_experience_profile(key)
    name = profile.display_name if profile else key
    emoji = profile.emoji if profile else "🎙️"
    lines = [
        "[GANTI GAYA OBROLAN — giliran berikutnya; lanjutkan alur, jangan reset topik]",
        f"Mode baru: {name} {emoji}",
    ]
    if prev and prev != key:
        prev_profile = get_experience_profile(prev)
        prev_name = prev_profile.display_name if prev_profile else prev
        lines.append(f"(dari {prev_name})")
    scenario_lines = scenario_prompt_lines(key, dialect=dialect, language=language)
    if scenario_lines:
        lines.extend(scenario_lines[:10])
    extra = natural_s2s_mode_lines(key, dialect=dialect, language=language)
    if extra:
        lines.extend(extra)
    lines.append("Jangan sebut 'mode' atau 'sistem' ke user — cukup ubah gaya bicara.")
    return "\n".join(lines)
