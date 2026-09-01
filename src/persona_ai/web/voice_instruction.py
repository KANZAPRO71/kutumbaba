"""System instruction for Gemini Live — built from full Persona engine output."""

from __future__ import annotations

from persona_ai.coherence.bind import bind
from persona_ai.core.types import (
    BehaviorDirectiveVector,
    LLMRequest,
    Message,
    PersonalityProfile,
    PolicyConstraintsRef,
    QuestionPolicy,
    ResponseLength,
    SpeakAction,
    ToneShift,
    VoiceDirective,
)
from persona_ai.llm.prompt import build_system_prompt
from persona_ai.personality.apply import _LANGUAGE_PROMPTS, apply
from persona_ai.web.live_mode import LiveModeConfig
from persona_ai.web.time_awareness import TimeAwarenessConfig
from persona_ai.web.voice_config import LiveVoiceConfig

_GOVERNANCE_HEADER = "[PERSONA_GOVERNANCE]"


from persona_ai.memory.models import UserMemoryRecord
from persona_ai.web.session_memory import (
    collapse_history as _collapse_history,
    format_live_history_block,
    format_user_memory_block,
    post_call_summary,
)
from persona_ai.personality.papua_dialect_phrases import (
    ack_templates_papua,
    dialect_prompt_lines,
    is_papua_dialect,
    papua_friend_lines,
    papua_language_prompt,
    papua_steer_reminder,
)
from persona_ai.personality.papua_knowledge import knowledge_prompt_lines
from persona_ai.personality.papua_mop_intros import emotional_tag_prompt_lines
from persona_ai.personality.papua_mops import mop_prompt_lines
from persona_ai.personality.papua_music import music_prompt_lines
from persona_ai.personality.papua_kamus import kamus_prompt_lines
from persona_ai.personality.papua_biak import biak_prompt_lines
from persona_ai.personality.papua_tabi import tabi_prompt_lines
from persona_ai.personality.papua_gaul_jalanan import gaul_jalanan_prompt_lines
from persona_ai.personality.papua_ondo_wibawa import ondo_wibawa_prompt_lines
from persona_ai.personality.papua_pantun_gombalan import pantun_gombalan_prompt_lines
from persona_ai.personality.papua_developer_credit import developer_credit_prompt_lines
from persona_ai.personality.papua_stt_lexicon import stt_prompt_lines
from persona_ai.personality.papua_voice_prosody import (
    emotional_audio_prompt_lines,
    voice_prosody_prompt_lines,
)
from persona_ai.personality.papua_live_system_instruction import master_system_instruction_lines


def _append_session_memory(
    lines: list[str],
    history: list[Message] | None,
    *,
    dialect: str | None,
    post_call: dict | None = None,
    user_memories: list[UserMemoryRecord] | None = None,
) -> None:
    recap = format_live_history_block(
        history,
        post_call=post_call,
        dialect=dialect,
        user_memories=user_memories,
    )
    if recap:
        lines.extend(["", recap])


def pending_user_utterance(messages: list[Message] | None) -> str | None:
    """Last user line if the assistant has not answered it yet."""
    if not messages:
        return None
    usable = _collapse_history(list(messages))
    if not usable or usable[-1].role != "user":
        return None
    text = usable[-1].text.strip()
    return text or None


def baseline_voice_directive(profile: PersonalityProfile) -> VoiceDirective:
    """Preset personality bound the same way as a normal RESPOND turn."""
    bdv = BehaviorDirectiveVector(
        speak=SpeakAction.RESPOND,
        length=ResponseLength.NORMAL,
        questions=QuestionPolicy.NONE,
        question_budget=profile.question_budget_cap,
        tone_shift=ToneShift.STABLE,
        engagement_level=0.6,
    )
    expr = apply(profile, bdv)
    return bind(bdv, expr, profile)


def _time_context(profile: PersonalityProfile) -> tuple[str | None, str]:
    lang = profile.default_language or "id"
    time_cfg = TimeAwarenessConfig.from_profile(profile)
    return time_cfg.timezone, lang


def _agent_handbook_block(profile: PersonalityProfile) -> list[str]:
    voice_cfg = LiveVoiceConfig.from_profile(profile)
    lang = profile.default_language or "id"
    handbook = voice_cfg.handbook_config(profile)
    sections = handbook.prompt_sections(language=lang)
    if not sections:
        return []
    lines = ["Agent Handbook (Retell-mapped presets):"]
    for title, block in sections:
        lines.append(f"{title}:")
        lines.extend(f"- {line}" for line in block)
    lines.append("")
    return lines


def _pronunciation_block(profile: PersonalityProfile) -> list[str]:
    voice_cfg = LiveVoiceConfig.from_profile(profile)
    lines = voice_cfg.pronunciation_lines()
    if not lines:
        return []
    return [*lines, ""]


def _transcription_hints_block(profile: PersonalityProfile) -> list[str]:
    voice_cfg = LiveVoiceConfig.from_profile(profile)
    lines = voice_cfg.transcription_hint_lines()
    if not lines:
        return []
    return ["Transcription hints (Retell boosted keywords):", *lines, ""]


def _friend_conversation_lines(profile: PersonalityProfile, *, dialect: str | None = None) -> list[str]:
    """Companion voice — teman ngobrol, bukan asisten yang wawancara."""
    if is_papua_dialect(dialect) and (profile.default_language or "id") == "id":
        return papua_friend_lines()
    if (profile.default_language or "id") == "id":
        return [
            "Peranmu: teman ngobrol, bukan asisten layanan atau chatbot FAQ.",
            "Ikut alur obrolan — tanggapi, cerita, atau kasih opini singkat.",
            "Jangan wawancara user dengan pertanyaan demi pertanyaan.",
            "Setelah jawab, berhenti dan dengarkan — biarkan user yang lanjut kalau mau.",
        ]
    return [
        "You are a friend chatting, not a customer-service assistant or FAQ bot.",
        "Follow the conversation — react, share, or give a short take.",
        "Do not interview the user with question after question.",
        "After you respond, stop and listen — let the user continue when they want.",
    ]


def _no_checkin_question_lines(profile: PersonalityProfile, *, dialect: str | None = None) -> list[str]:
    """Keep live voice from ending every turn like a call-center bot."""
    if profile.question_budget_cap <= 0:
        lines = [
            "Do not ask the user any question unless one missing fact makes an answer impossible.",
            "Never end with a question mark or a check-in closer.",
            "Do not use assistant-style follow-ups ('anything else', 'how can I help', 'what else').",
            "Jangan tanya 'ada yang mau ditanyakan', 'ada lagi yang mau kamu tanyakan', "
            "'ada lagi', 'butuh bantuan apa', 'ada yang bisa dibantu', "
            "'mau bahas apa lagi', 'apa lagi yang bisa', 'mau tanyakan apa lagi', "
            "atau 'anything else'.",
            "Jawab langsung, lalu berhenti dan dengarkan — biarkan user yang lanjut kalau mau.",
        ]
        if is_papua_dialect(dialect) and (profile.default_language or "id") == "id":
            lines.append(
                "Satu pengecualian: sesekali boleh tawarin Mop — satu pertanyaan singkat saja "
                "(contoh: Ko mo dengar sa pu Mop kah?) saat obrolan ringan; max ~1x per beberapa menit."
            )
    else:
        lines = [
            "Never use chatbot check-in closers ('ada yang mau ditanyakan', 'anything else').",
            f"Ask at most {profile.question_budget_cap} clarifying question(s) only when required, "
            "then stop.",
        ]
    for phrase in profile.lexicon_avoided:
        cleaned = phrase.strip()
        if cleaned:
            lines.append(f"Never say: {cleaned}.")
    return lines


def _papua_audio_system_lines(dialect: str | None, *, language: str = "id") -> list[str]:
    """STT tuning + prosody + ekspresi suara untuk dialect Papua."""
    lines: list[str] = []
    stt = stt_prompt_lines(dialect, language=language)
    if stt:
        lines.extend(stt)
    prosody = voice_prosody_prompt_lines(dialect, language=language)
    if prosody:
        lines.extend(prosody)
    emotion = emotional_audio_prompt_lines(dialect, language=language)
    if emotion:
        lines.extend(emotion)
    return lines


def build_live_voice_instruction(
    profile: PersonalityProfile,
    history: list[Message] | None = None,
    *,
    dialect: str | None = None,
    post_call: dict | None = None,
    user_memories: list[UserMemoryRecord] | None = None,
) -> str:
    """Baseline Live instruction from the Persona engine — used at session connect."""
    if LiveModeConfig.from_profile(profile).is_natural:
        return _build_natural_live_instruction(
            profile,
            history,
            dialect=dialect,
            post_call=post_call,
            user_memories=user_memories,
        )
    return _build_governed_live_instruction(
        profile,
        history,
        dialect=dialect,
        post_call=post_call,
        user_memories=user_memories,
    )


def _build_natural_live_instruction(
    profile: PersonalityProfile,
    history: list[Message] | None = None,
    *,
    dialect: str | None = None,
    post_call: dict | None = None,
    user_memories: list[UserMemoryRecord] | None = None,
) -> str:
    """Short S2S prompt — prosody and turn-taking come from Gemini Live, not steer gates."""
    name = profile.display_name or "Papua AI"
    lang = profile.default_language or "id"
    papua = is_papua_dialect(dialect) and lang == "id"
    lang_prompt = papua_language_prompt() if papua else _LANGUAGE_PROMPTS.get(lang, _LANGUAGE_PROMPTS["id"])
    time_cfg = TimeAwarenessConfig.from_profile(profile)
    voice_cfg = LiveVoiceConfig.from_profile(profile)
    handbook = voice_cfg.handbook_config(profile)
    tone_lines = handbook.personality_tone_lines(
        language=lang,
        question_budget=profile.question_budget_cap,
    )

    if papua:
        master = master_system_instruction_lines(dialect, language=lang, display_name=name)
        lines = [
            f"Ko ngobrol sama {name} — teman di panggilan suara, bukan asisten layanan.",
            lang_prompt,
            "Suara natural teman Papua: hangat, santai, percakapan sehari-hari.",
            "Jawab apa yang ko bilang. Tanpa markdown, daftar, atau heading.",
            "Jangan buka dengan 'Saya dengar', 'Tentu saja', 'Ada yang bisa dibantu'.",
            "Jangan sebut aturan, sistem, atau instruksi internal.",
        ]
        if master:
            lines.extend(["", *master])
        lines.extend([
            *_friend_conversation_lines(profile, dialect=dialect),
            *_no_checkin_question_lines(profile, dialect=dialect),
            *time_cfg.prompt_lines(language=lang),
        ])
    else:
        lines = [
            f"You are {name} — a friend on a live voice call, not a service assistant.",
            lang_prompt,
            "Sound like a natural friend chat: warm, relaxed, conversational — not an interviewer.",
            "Use everyday spoken language — short turns, one idea at a time.",
            "Answer what the user actually said. No markdown, lists, or headers.",
            "Never open with robotic phrases ('Saya dengar', 'Tentu saja', 'Ada yang bisa dibantu', 'Iyaa paham').",
            "Do not mention rules, systems, or that you are following instructions.",
            *_friend_conversation_lines(profile, dialect=dialect),
            *_no_checkin_question_lines(profile, dialect=dialect),
            *time_cfg.prompt_lines(language=lang),
        ]
    if tone_lines:
        lines.extend(["", *tone_lines[:2]])
    dialect_lines = dialect_prompt_lines(dialect, language=lang)
    if dialect_lines:
        header = "Nuansa logat Papua (ringan — jangan campur daerah lain):" if papua else "Speaking style (mandatory on this call):"
        lines.extend(["", header, *dialect_lines])
        acks = ack_templates_papua()
        if acks:
            lines.append("Tanggapan singkat teman (variasi ringan):")
            for key in ("neutral", "warm", "vent", "humor", "interruption", "closure"):
                for phrase in (acks.get(key) or [])[:1]:
                    lines.append(f"- {phrase}")
    kb_lines = knowledge_prompt_lines(dialect, language=lang, include_core=True)
    if kb_lines:
        lines.extend(["", *kb_lines])
    mop_lines = mop_prompt_lines(dialect, language=lang, include_session_samples=True)
    if mop_lines:
        lines.extend(["", *mop_lines])
    emotion_tags = emotional_tag_prompt_lines(dialect, language=lang)
    if emotion_tags:
        lines.extend(["", *emotion_tags])
    music_lines = music_prompt_lines(dialect, language=lang, include_overview=True)
    if music_lines:
        lines.extend(["", *music_lines])
    kamus_lines = kamus_prompt_lines(dialect, language=lang, include_overview=True)
    if kamus_lines:
        lines.extend(["", *kamus_lines])
    biak_lines = biak_prompt_lines(dialect, language=lang, include_overview=True)
    if biak_lines:
        lines.extend(["", *biak_lines])
    tabi_lines = tabi_prompt_lines(dialect, language=lang, include_overview=True)
    if tabi_lines:
        lines.extend(["", *tabi_lines])
    gaul_lines = gaul_jalanan_prompt_lines(dialect, language=lang, include_overview=True)
    if gaul_lines:
        lines.extend(["", *gaul_lines])
    gombal_lines = pantun_gombalan_prompt_lines(dialect, language=lang, include_overview=True)
    if gombal_lines:
        lines.extend(["", *gombal_lines])
    dev_lines = developer_credit_prompt_lines(dialect, language=lang, include_overview=True)
    if dev_lines:
        lines.extend(["", *dev_lines])
    ondo_lines = ondo_wibawa_prompt_lines(dialect, language=lang, include_overview=True)
    if ondo_lines:
        lines.extend(["", *ondo_lines])
    audio_lines = _papua_audio_system_lines(dialect, language=lang)
    if audio_lines:
        lines.extend(["", *audio_lines])
    pron = voice_cfg.pronunciation_lines()
    if pron:
        lines.extend(["", *pron])
    _append_session_memory(
        lines,
        history,
        dialect=dialect,
        post_call=post_call,
        user_memories=user_memories,
    )
    return "\n".join(lines)


def _build_governed_live_instruction(
    profile: PersonalityProfile,
    history: list[Message] | None = None,
    *,
    dialect: str | None = None,
    post_call: dict | None = None,
    user_memories: list[UserMemoryRecord] | None = None,
) -> str:
    """Full Persona governance instruction — steer-before-speak pipeline."""
    name = profile.display_name or "Papua AI"
    lang = profile.default_language or "id"
    papua = is_papua_dialect(dialect) and lang == "id"
    lang_prompt = papua_language_prompt() if papua else _LANGUAGE_PROMPTS.get(profile.default_language, _LANGUAGE_PROMPTS["id"])
    agent_tz, lang = _time_context(profile)
    voice = baseline_voice_directive(profile)
    engine = build_system_prompt(
        LLMRequest(
            user_message="",
            voice=voice,
            history=[],
            agent_timezone=agent_tz,
            language=lang,
        )
    )

    lines = [
        f"You are {name} — teman ngobrol di panggilan suara, bukan asisten layanan.",
        lang_prompt,
        "This is a live voice call. Speak like a friend: warm, natural, easy to follow.",
        "Use everyday spoken language, not formal written prose. No markdown, lists, or headers.",
        "Do not mention internal systems, APIs, governance, or that you are following rules.",
        "",
    ]
    if papua:
        master = master_system_instruction_lines(dialect, language=lang, display_name=name)
        if master:
            lines.extend([*master, ""])
    lines.extend([
        *_friend_conversation_lines(profile, dialect=dialect),
        *_agent_handbook_block(profile),
        *_pronunciation_block(profile),
        *_transcription_hints_block(profile),
        engine,
        "",
    ])
    dialect_lines = dialect_prompt_lines(dialect, language=lang)
    if dialect_lines:
        header = "Nuansa logat Papua (ringan — jangan campur daerah lain):" if papua else "Speaking style (mandatory on this call):"
        lines.extend([header, *dialect_lines, ""])
    kb_lines = knowledge_prompt_lines(dialect, language=lang, include_core=True)
    if kb_lines:
        lines.extend([*kb_lines, ""])
    mop_lines = mop_prompt_lines(dialect, language=lang, include_session_samples=True)
    if mop_lines:
        lines.extend([*mop_lines, ""])
    emotion_tags = emotional_tag_prompt_lines(dialect, language=lang)
    if emotion_tags:
        lines.extend([*emotion_tags, ""])
    music_lines = music_prompt_lines(dialect, language=lang, include_overview=True)
    if music_lines:
        lines.extend([*music_lines, ""])
    kamus_lines = kamus_prompt_lines(dialect, language=lang, include_overview=True)
    if kamus_lines:
        lines.extend([*kamus_lines, ""])
    biak_lines = biak_prompt_lines(dialect, language=lang, include_overview=True)
    if biak_lines:
        lines.extend([*biak_lines, ""])
    tabi_lines = tabi_prompt_lines(dialect, language=lang, include_overview=True)
    if tabi_lines:
        lines.extend([*tabi_lines, ""])
    gaul_lines = gaul_jalanan_prompt_lines(dialect, language=lang, include_overview=True)
    if gaul_lines:
        lines.extend([*gaul_lines, ""])
    gombal_lines = pantun_gombalan_prompt_lines(dialect, language=lang, include_overview=True)
    if gombal_lines:
        lines.extend([*gombal_lines, ""])
    dev_lines = developer_credit_prompt_lines(dialect, language=lang, include_overview=True)
    if dev_lines:
        lines.extend([*dev_lines, ""])
    ondo_lines = ondo_wibawa_prompt_lines(dialect, language=lang, include_overview=True)
    if ondo_lines:
        lines.extend([*ondo_lines, ""])
    audio_lines = _papua_audio_system_lines(dialect, language=lang)
    if audio_lines:
        lines.extend([*audio_lines, ""])
    lines.extend(
        [
        "Turn protocol (mandatory):",
        "You hear the user's audio. A Persona engine decides whether and how you may speak.",
        f"- Messages starting with {_GOVERNANCE_HEADER} are engine directives, not user speech.",
        "- SPEAK: say only the provided line, naturally, in one breath.",
        "- ENGINE: answer the user's spoken audio under the appended constraints. "
        "Do not read the constraints aloud.",
        "- If Questions you may ask is 0: do not ask anything. Do not end with a question. "
        "Jangan tanya 'ada yang mau ditanyakan', 'butuh bantuan apa', atau 'ada lagi'.",
        "- After you finish a reply, stop and listen.",
        "- If no governance message arrives, wait. Do not improvise a second reply.",
        ]
    )
    recap = format_live_history_block(
        history,
        post_call=post_call,
        dialect=dialect,
        user_memories=user_memories,
    )
    if recap:
        lines.extend(["", recap])
    return "\n".join(lines)


def build_live_engine_instruction(
    profile: PersonalityProfile,
    voice: VoiceDirective,
    *,
    policy_constraints: PolicyConstraintsRef | None = None,
    history: list[Message] | None = None,
    dialect: str | None = None,
    post_call: dict | None = None,
    user_memories: list[UserMemoryRecord] | None = None,
) -> str:
    """Live instruction merged with VoiceDirective + the actual conversation thread."""
    lang = profile.default_language or "id"
    papua = is_papua_dialect(dialect) and lang == "id"
    spoken = [
        "Live voice call — speak naturally, no markdown.",
        papua_language_prompt() if papua else _LANGUAGE_PROMPTS.get(lang, _LANGUAGE_PROMPTS["id"]),
        f"Spoken action this turn: {voice.speak.value}.",
        f"Name: {profile.display_name or 'Papua AI'}.",
    ]
    if papua:
        spoken.append(papua_steer_reminder())
    user_line = pending_user_utterance(history)
    kb_turn = knowledge_prompt_lines(
        dialect, language=lang, query=user_line, include_core=False
    )
    if kb_turn:
        spoken.extend(["", *kb_turn])
    mop_turn = mop_prompt_lines(
        dialect, language=lang, query=user_line, include_session_samples=False
    )
    if mop_turn:
        spoken.extend(["", *mop_turn])
    music_turn = music_prompt_lines(
        dialect, language=lang, query=user_line, include_overview=False
    )
    if music_turn:
        spoken.extend(["", *music_turn])
    kamus_turn = kamus_prompt_lines(
        dialect, language=lang, query=user_line, include_overview=False
    )
    if kamus_turn:
        spoken.extend(["", *kamus_turn])
    biak_turn = biak_prompt_lines(
        dialect, language=lang, query=user_line, include_overview=False
    )
    if biak_turn:
        spoken.extend(["", *biak_turn])
    tabi_turn = tabi_prompt_lines(
        dialect, language=lang, query=user_line, include_overview=False
    )
    if tabi_turn:
        spoken.extend(["", *tabi_turn])
    gaul_turn = gaul_jalanan_prompt_lines(
        dialect, language=lang, query=user_line, include_overview=False
    )
    if gaul_turn:
        spoken.extend(["", *gaul_turn])
    gombal_turn = pantun_gombalan_prompt_lines(
        dialect, language=lang, query=user_line, include_overview=False
    )
    if gombal_turn:
        spoken.extend(["", *gombal_turn])
    dev_turn = developer_credit_prompt_lines(
        dialect, language=lang, query=user_line, include_overview=True
    )
    if dev_turn:
        spoken.extend(["", *dev_turn])
    ondo_turn = ondo_wibawa_prompt_lines(
        dialect, language=lang, query=user_line, include_overview=False
    )
    if ondo_turn:
        spoken.extend(["", *ondo_turn])
    audio_turn = _papua_audio_system_lines(dialect, language=lang)
    if audio_turn:
        spoken.extend(["", *audio_turn])
    spoken.extend(_agent_handbook_block(profile))
    recap = format_live_history_block(
        history,
        post_call=post_call,
        dialect=dialect,
        user_memories=user_memories,
    )
    if recap:
        spoken.extend(
            [
                recap,
                "Use that thread. The latest user line is what you answer now.",
            ]
        )
    agent_tz, lang = _time_context(profile)
    req = LLMRequest(
        user_message="",
        voice=voice,
        history=list(history or []),
        policy_constraints=policy_constraints,
        agent_timezone=agent_tz,
        language=lang,
    )
    engine = build_system_prompt(req)
    if papua:
        spoken.extend(["", papua_steer_reminder()])
    return "\n".join(spoken + ["", engine])


def build_speak_directive(*, bdv: str, text: str, ack_only: bool = False, dialect: str | None = None) -> str:
    papua = is_papua_dialect(dialect)
    style = (
        "Say naturally in Papuan urban Indonesian (sa/ko only, no markdown):"
        if papua
        else "Say naturally in spoken Bahasa Indonesia (no markdown):"
    )
    lines = [
        _GOVERNANCE_HEADER,
        "Action: SPEAK",
        f"BDV: {bdv}",
        style,
        f'"{text.strip()}"',
    ]
    if papua:
        lines.append(papua_steer_reminder())
    if ack_only or bdv == SpeakAction.ACK_ONLY.value:
        lines.append("One short sentence only — brief acknowledgment, not a full answer.")
    return "\n".join(lines)


def build_engine_directive(instruction: str, *, dialect: str | None = None) -> str:
    papua = is_papua_dialect(dialect)
    opener = (
        "Do not open with robotic listening openers — answer directly in sa/ko Papuan style."
        if papua
        else "Do not open with robotic listening openers (e.g. 'Aku dengerin', 'Saya dengar') — answer directly. "
        "Light natural fillers mid-sentence are fine when spoken-style allows."
    )
    lines = [
        _GOVERNANCE_HEADER,
        "Action: ENGINE",
        "The user just finished speaking — you heard their audio.",
        "Reply once in your live voice. Do not read these constraints aloud.",
        "You are a friend chatting — not a service assistant. Do not ask check-in closers.",
        opener,
    ]
    if papua:
        lines.append(papua_steer_reminder())
    lines.append(instruction.strip())
    return "\n".join(lines)


def build_engine_directive_for_transcript(transcript: str, instruction: str, *, dialect: str | None = None) -> str:
    """Steer after activity closed — Gemini did not retain the mic audio in-turn."""
    cleaned = transcript.strip()
    papua = is_papua_dialect(dialect)
    opener = (
        "Do not open with robotic listening openers — answer directly in sa/ko Papuan style."
        if papua
        else "Do not open with robotic listening openers (e.g. 'Aku dengerin', 'Saya dengar') — answer directly. "
        "Light natural fillers mid-sentence are fine when spoken-style allows."
    )
    lines = [
        _GOVERNANCE_HEADER,
        "Action: ENGINE",
        f'The user said: "{cleaned}"',
        "Reply once in your live voice to what they said. Do not read these constraints aloud.",
        opener,
    ]
    if papua:
        lines.append(papua_steer_reminder())
    lines.append(instruction.strip())
    return "\n".join(lines)
