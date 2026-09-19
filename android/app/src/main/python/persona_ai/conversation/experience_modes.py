"""Experience Mode — product layer above scenario_id / BDV (not a new pipeline)."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from persona_ai.conversation.scenarios import DEFAULT_SCENARIO_ID

DEFAULT_EXPERIENCE_MODE_ID = "nongkrong"

ResponseStyle = Literal["ultra_short", "short", "normal"]
EnergyLevel = Literal["low", "adaptive", "high"]
InterruptionPolicy = Literal["low", "normal", "forbidden"]


class BehaviorProfile(BaseModel):
    response_style: ResponseStyle = "short"
    question_budget: int = Field(default=1, ge=0, le=3)
    ack_bias: float = Field(default=0.35, ge=0.0, le=1.0)
    silence_allowed: bool = True
    defer_bias: float = Field(default=0.0, ge=0.0, le=1.0)
    energy: EnergyLevel = "adaptive"
    warmth_bias: float = Field(default=0.0, ge=-0.3, le=0.3)
    listen_ratio_hint: float = Field(default=0.5, ge=0.0, le=1.0)


class LiveGovernanceProfile(BaseModel):
    """Maps to ConversationController steer templates — not PCM / VAD."""

    steer_profile: str = "casual_chat"
    allow_proactive_question: bool = True
    max_response_words: int = Field(default=55, ge=12, le=160)
    interruption_policy: InterruptionPolicy = "normal"
    deliver_steer: bool = True


class AudioPolicy(BaseModel):
    reactions: bool = True
    laugh_track: bool = False
    bgm: str | None = None


class CallbackPolicy(BaseModel):
    enabled: bool = True
    max_per_day: int = Field(default=1, ge=0, le=5)
    selective: bool = False


class MopPhase(str, Enum):
    IDLE = "IDLE"
    SETUP = "SETUP"
    HOLD = "HOLD"
    PUNCHLINE = "PUNCHLINE"
    REACTION = "REACTION"
    COOLDOWN = "COOLDOWN"


class ExperienceModeProfile(BaseModel):
    id: str
    scenario_id: str
    display_name: str
    emoji: str
    tagline: str
    behavior: BehaviorProfile = Field(default_factory=BehaviorProfile)
    live: LiveGovernanceProfile = Field(default_factory=LiveGovernanceProfile)
    audio: AudioPolicy = Field(default_factory=AudioPolicy)
    callback: CallbackPolicy = Field(default_factory=CallbackPolicy)


_EXPERIENCE_MODES: dict[str, ExperienceModeProfile] = {
    "nongkrong": ExperienceModeProfile(
        id="nongkrong",
        scenario_id="casual_chat",
        display_name="Nongkrong",
        emoji="🎙️",
        tagline="Ngobrol santai seperti teman.",
        behavior=BehaviorProfile(
            response_style="short",
            question_budget=1,
            ack_bias=0.4,
            silence_allowed=True,
            energy="adaptive",
        ),
        live=LiveGovernanceProfile(
            steer_profile="casual_chat",
            max_response_words=48,
        ),
        audio=AudioPolicy(reactions=True, laugh_track=False, bgm=None),
        callback=CallbackPolicy(enabled=True, max_per_day=1),
    ),
    "mop": ExperienceModeProfile(
        id="mop",
        scenario_id="funny",
        display_name="Mop",
        emoji="😂",
        tagline="Humor Papua — setup, jeda, punchline.",
        behavior=BehaviorProfile(
            response_style="short",
            question_budget=0,
            ack_bias=0.35,
            energy="high",
        ),
        live=LiveGovernanceProfile(
            steer_profile="funny",
            max_response_words=52,
            allow_proactive_question=False,
        ),
        audio=AudioPolicy(reactions=True, laugh_track=True, bgm="disko_tanah"),
        callback=CallbackPolicy(enabled=True, max_per_day=1),
    ),
    "cerita_tong": ExperienceModeProfile(
        id="cerita_tong",
        scenario_id="curhat",
        display_name="Cerita Tong",
        emoji="🗣️",
        tagline="Ko cerita — Tra dengar dulu.",
        behavior=BehaviorProfile(
            response_style="short",
            question_budget=1,
            ack_bias=0.55,
            silence_allowed=True,
            defer_bias=0.45,
            energy="low",
            warmth_bias=0.15,
            listen_ratio_hint=0.85,
        ),
        live=LiveGovernanceProfile(
            steer_profile="curhat",
            max_response_words=32,
            allow_proactive_question=False,
        ),
        audio=AudioPolicy(reactions=True, laugh_track=False),
        callback=CallbackPolicy(enabled=True, max_per_day=1, selective=True),
    ),
    "teman_malam": ExperienceModeProfile(
        id="teman_malam",
        scenario_id="casual_chat",
        display_name="Teman Malam",
        emoji="🌙",
        tagline="Tenang, hangat, tidak ramai.",
        behavior=BehaviorProfile(
            response_style="short",
            question_budget=0,
            ack_bias=0.45,
            silence_allowed=True,
            energy="low",
            warmth_bias=0.2,
            listen_ratio_hint=0.7,
        ),
        live=LiveGovernanceProfile(
            steer_profile="curhat",
            max_response_words=28,
            allow_proactive_question=False,
        ),
        audio=AudioPolicy(reactions=True, laugh_track=False, bgm="malam"),
        callback=CallbackPolicy(enabled=True, max_per_day=1, selective=True),
    ),
    "teman_jalan": ExperienceModeProfile(
        id="teman_jalan",
        scenario_id="casual_chat",
        display_name="Teman Jalan",
        emoji="🚶",
        tagline="Respons super singkat — ko lagi jalan.",
        behavior=BehaviorProfile(
            response_style="ultra_short",
            question_budget=0,
            ack_bias=0.65,
            silence_allowed=True,
            defer_bias=0.2,
            energy="low",
            listen_ratio_hint=0.75,
        ),
        live=LiveGovernanceProfile(
            steer_profile="curhat",
            max_response_words=18,
            interruption_policy="forbidden",
            allow_proactive_question=False,
        ),
        audio=AudioPolicy(reactions=True, laugh_track=False),
        callback=CallbackPolicy(enabled=False, max_per_day=0),
    ),
}

_LEGACY_TO_EXPERIENCE: dict[str, str] = {
    "casual_chat": "nongkrong",
    "funny": "mop",
    "curhat": "cerita_tong",
}

_EXPERIENCE_ORDER = (
    "nongkrong",
    "mop",
    "cerita_tong",
    "teman_malam",
    "teman_jalan",
)


def normalize_experience_mode(mode: str | None) -> str:
    key = (mode or "").strip().lower()
    if not key:
        return DEFAULT_EXPERIENCE_MODE_ID
    if key in _EXPERIENCE_MODES:
        return key
    if key in _LEGACY_TO_EXPERIENCE:
        return _LEGACY_TO_EXPERIENCE[key]
    return key


def get_experience_profile(mode: str | None) -> ExperienceModeProfile | None:
    key = normalize_experience_mode(mode)
    if key in _EXPERIENCE_MODES:
        return _EXPERIENCE_MODES[key]
    return None


def scenario_id_for_mode(mode: str | None) -> str:
    profile = get_experience_profile(mode)
    if profile is not None:
        return profile.scenario_id
    key = (mode or "").strip().lower() or DEFAULT_SCENARIO_ID
    return key


def live_steer_profile_for_mode(mode: str | None) -> str:
    profile = get_experience_profile(mode)
    if profile is not None:
        return profile.live.steer_profile
    return (mode or DEFAULT_SCENARIO_ID).strip().lower() or DEFAULT_SCENARIO_ID


def list_experience_modes() -> list[ExperienceModeProfile]:
    return [_EXPERIENCE_MODES[mid] for mid in _EXPERIENCE_ORDER if mid in _EXPERIENCE_MODES]


def experience_mode_for_client(profile: ExperienceModeProfile) -> dict[str, str]:
    return {
        "id": profile.id,
        "display_name": profile.display_name,
        "emoji": profile.emoji,
        "tagline": profile.tagline,
        "scenario_id": profile.scenario_id,
        "audio_bgm": profile.audio.bgm or "",
        "laugh_track": "1" if profile.audio.laugh_track else "0",
    }


def should_callback(
    *,
    mode: str | None,
    loop_priority: float,
    mentioned_today: bool,
    callbacks_used_today: int,
    min_priority: float = 0.35,
) -> bool:
    from persona_ai.conversation.callback_gate import should_callback as _gate_should

    return _gate_should(
        mode=mode,
        loop_priority=loop_priority,
        mentioned_today=mentioned_today,
        callbacks_used_today=callbacks_used_today,
        min_priority=min_priority,
    )
