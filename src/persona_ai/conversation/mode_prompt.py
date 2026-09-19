"""Format conversation mode blocks for Live system instructions."""

from __future__ import annotations

from persona_ai.conversation.scenarios import ConversationScenario, get_scenario


def scenario_prompt_lines(
    scenario_id: str | None,
    *,
    dialect: str | None = None,
    language: str | None = "id",
) -> list[str]:
    scenario = get_scenario(scenario_id)
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
    from persona_ai.conversation.scenarios import DEFAULT_SCENARIO_ID

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
