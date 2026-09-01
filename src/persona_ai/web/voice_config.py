"""Live voice tuning — Retell-style naturalness params mapped to Gemini Live."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from persona_ai.core.types import PersonalityProfile
from persona_ai.personality.preset import read_preset_json
from persona_ai.web.agent_handbook import AgentHandbookConfig

DEFAULT_LIVE_VOICE_NAME = "Leda"
DEFAULT_LIVE_LANGUAGE_CODE = "id-ID"

# Gemini Live prebuilt voices (curated for UI — full set in Google docs).
GEMINI_LIVE_VOICES: tuple[dict[str, str], ...] = (
    {"name": "Sulafat", "style": "Hangat"},
    {"name": "Leda", "style": "Muda"},
    {"name": "Aoede", "style": "Ringan"},
    {"name": "Vindemiatrix", "style": "Lembut"},
    {"name": "Callirrhoe", "style": "Santai"},
    {"name": "Kore", "style": "Tegas"},
    {"name": "Puck", "style": "Ceria"},
    {"name": "Charon", "style": "Informatif"},
    {"name": "Fenrir", "style": "Antusias"},
    {"name": "Zephyr", "style": "Terang"},
    {"name": "Achird", "style": "Ramah"},
    {"name": "Gacrux", "style": "Dewasa"},
    {"name": "Schedar", "style": "Tenang"},
    {"name": "Enceladus", "style": "Breathy"},
    {"name": "Sadachbia", "style": "Hidup"},
)

_VALID_VOICE_NAMES = frozenset(v["name"] for v in GEMINI_LIVE_VOICES)


def list_live_voices() -> list[dict[str, str]]:
    return [{"name": v["name"], "style": v["style"]} for v in GEMINI_LIVE_VOICES]


def normalize_voice_name(name: str | None) -> str:
    if not name or not isinstance(name, str):
        return DEFAULT_LIVE_VOICE_NAME
    cleaned = name.strip()
    if cleaned in _VALID_VOICE_NAMES:
        return cleaned
    # Case-insensitive match
    lower = cleaned.lower()
    for v in GEMINI_LIVE_VOICES:
        if v["name"].lower() == lower:
            return v["name"]
    return DEFAULT_LIVE_VOICE_NAME


# No canned spoken opener — Gemini greets naturally from the live instruction.
RETELL_DEFAULT_BEGIN_MESSAGE = None

_VALID_DENOISING = frozenset(
    {"remove_noise", "remove_noise_and_background_speech", "none", "no_denoising"}
)
_VALID_TRANSCRIPTION_MODES = frozenset({"speed", "accuracy", "custom"})


@dataclass(frozen=True)
class PronunciationGuide:
    """Retell pronunciation entry — IPA/CMU/plain hint for TTS."""

    word: str
    guide: str


@dataclass(frozen=True)
class LiveVoiceConfig:
    """Orchestration tuning mapped from Retell Create Agent speech settings."""

    responsiveness: float = 1.0
    interruption_sensitivity: float = 1.0
    enable_dynamic_responsiveness: bool = True
    enable_backchannel: bool = True
    backchannel_frequency: float = 0.8
    start_speaker: str = "agent"  # "agent" | "user"
    begin_message: str | None = None
    begin_message_delay_ms: int = 1000
    speech_flexibility: float = 0.8
    enable_speech_normalization: bool = True
    denoising: str = "remove_noise_and_background_speech"
    transcription_mode: str = "custom"  # speed | accuracy | custom
    boosted_keywords: tuple[str, ...] = ()
    background_sound: str | None = None
    # Retell Speech Style / tone modifiers
    default_tone: str = "professional_conversational"  # professional | professional_conversational
    enable_natural_fillers: bool = True
    enable_high_empathy: bool = False
    pronunciations: tuple[PronunciationGuide, ...] = ()
    voice_name: str = DEFAULT_LIVE_VOICE_NAME
    language_code: str = DEFAULT_LIVE_LANGUAGE_CODE
    generation_temperature: float = 0.68

    def __post_init__(self) -> None:
        if not 0.0 <= self.responsiveness <= 1.0:
            raise ValueError("responsiveness must be 0–1")
        if not 0.0 <= self.generation_temperature <= 2.0:
            raise ValueError("generation_temperature must be 0–2")
        if not 0.0 <= self.interruption_sensitivity <= 1.0:
            raise ValueError("interruption_sensitivity must be 0–1")
        if not 0.0 <= self.backchannel_frequency <= 1.0:
            raise ValueError("backchannel_frequency must be 0–1")
        if not 0.0 <= self.speech_flexibility <= 1.0:
            raise ValueError("speech_flexibility must be 0–1")
        if self.begin_message_delay_ms < 0:
            raise ValueError("begin_message_delay_ms must be >= 0")
        if self.default_tone not in (
            "professional",
            "professional_conversational",
            "companion_friend",
        ):
            raise ValueError(
                "default_tone must be professional, professional_conversational, or companion_friend"
            )
        if self.start_speaker not in ("agent", "user"):
            raise ValueError("start_speaker must be agent or user")
        if self.background_sound is not None and not isinstance(self.background_sound, str):
            raise ValueError("background_sound must be a string or None")
        if self.denoising not in _VALID_DENOISING:
            raise ValueError(
                "denoising must be remove_noise, remove_noise_and_background_speech, or none"
            )
        if self.transcription_mode not in _VALID_TRANSCRIPTION_MODES:
            raise ValueError("transcription_mode must be speed, accuracy, or custom")
        object.__setattr__(self, "voice_name", normalize_voice_name(self.voice_name))

    def effective_speech_flexibility(self) -> float:
        """Retell transcription mode — speed vs accuracy vs custom slider."""
        if self.transcription_mode == "speed":
            return 1.0
        if self.transcription_mode == "accuracy":
            return 0.2
        return self.speech_flexibility

    def partial_min_chars(self) -> int:
        flex = self.effective_speech_flexibility()
        if self.transcription_mode == "speed":
            return 4
        if self.transcription_mode == "accuracy":
            return 12
        return max(4, int(round(8 - flex * 2)))

    def final_transcript_timeout_s(self) -> float:
        flex = self.effective_speech_flexibility()
        if self.transcription_mode == "speed":
            return 0.25
        if self.transcription_mode == "accuracy":
            return 0.75
        return 0.15 + (1.0 - flex) * 0.30

    def max_asr_wait_after_end_s(self) -> float:
        if self.transcription_mode == "speed":
            return 8.0
        if self.transcription_mode == "accuracy":
            return 15.0
        return 12.0

    def input_transcription_config(self):
        """Gemini Live ASR — custom_vocabulary maps Retell boosted keywords."""
        from google.genai import types

        kwargs: dict = {"language_codes": [self.language_code]}
        vocab = [k.strip() for k in self.boosted_keywords if k and k.strip()]
        if vocab:
            kwargs["custom_vocabulary"] = vocab
        # Live governance needs verbatim user lines — SMART strips fillers mid-turn.
        kwargs["mode"] = types.AudioTranscriptionConfigMode.VERBATIM
        return types.AudioTranscriptionConfig(**kwargs)

    def transcription_hint_lines(self) -> list[str]:
        """Fallback ASR hints when provider vocabulary API is unavailable."""
        if not self.boosted_keywords:
            return []
        words = ", ".join(self.boosted_keywords)
        return [
            f"User speech may include these terms — transcribe them faithfully: {words}.",
        ]

    def effective_responsiveness(
        self,
        *,
        transcript: str = "",
        voice_pause_ms: int = 0,
    ) -> float:
        """Retell dynamic eagerness — short/fast turns stay eager; long pauses get extra wait."""
        if not self.enable_dynamic_responsiveness:
            return self.responsiveness
        base = self.responsiveness
        words = len(transcript.split()) if transcript.strip() else 0
        if words <= 3:
            return min(1.0, base + 0.05)
        if voice_pause_ms >= 1200:
            return max(0.0, base - 0.15)
        if words >= 18:
            return max(0.0, base - 0.08)
        return base

    def effective_silence_duration_ms(
        self,
        *,
        transcript: str = "",
        voice_pause_ms: int = 0,
    ) -> int:
        resp = self.effective_responsiveness(
            transcript=transcript, voice_pause_ms=voice_pause_ms
        )
        extra = int(round((1.0 - resp) * 5000))
        return 200 + extra

    def silence_duration_ms(self) -> int:
        """Retell: lowering responsiveness by 0.1 adds 500ms wait. Baseline = 200ms turn-taking."""
        extra = int(round((1.0 - self.responsiveness) * 5000))
        return 200 + extra

    def prefix_padding_ms(self) -> int:
        """Speech must last this long before VAD commits start-of-speech."""
        return int(120 + (1.0 - self.interruption_sensitivity) * 180)

    def barge_in_rms_threshold(self) -> float:
        """Client mic RMS — high enough to ignore laptop-speaker echo after AEC."""
        return 0.05 + (1.0 - self.interruption_sensitivity) * 0.05

    def barge_in_grace_ms(self) -> int:
        """Short beat of agent audio before a cut is allowed — ChatGPT-like interrupt."""
        return int(280 + (1.0 - self.interruption_sensitivity) * 500)

    def barge_in_sustain_frames(self) -> int:
        """~2.7ms/frame at 48kHz. Default ≈ 100ms of continuous speech, not a blip."""
        return int(36 + (1.0 - self.interruption_sensitivity) * 24)

    def barge_in_cooldown_ms(self) -> int:
        return int(450 + (1.0 - self.interruption_sensitivity) * 350)

    def partial_stability_s(self) -> float:
        """Retell transcription timing — higher flexibility = accept partials sooner."""
        flex = self.effective_speech_flexibility()
        return 0.10 + (1.0 - flex) * 0.10

    def stt_grace_after_silence_s(self) -> float:
        """Extra wait for ASR after VAD silence before flush/commit."""
        flex = self.effective_speech_flexibility()
        return 0.15 + (1.0 - flex) * 0.15

    def loud_mic_rms(self) -> float:
        """Retell denoising mode — stricter mic gate when aggressive."""
        mode = self.denoising
        if mode in ("remove_noise_and_background_speech",):
            return 0.05
        if mode in ("remove_noise",):
            return 0.045
        return 0.04

    def silence_reset_rms(self) -> float:
        mode = self.denoising
        if mode in ("remove_noise_and_background_speech",):
            return 0.046
        if mode in ("remove_noise",):
            return 0.042
        return 0.038

    def phantom_min_peak_rms(self) -> float:
        mode = self.denoising
        if mode in ("remove_noise_and_background_speech",):
            return 0.055
        return 0.05

    def live_thresholds(self) -> dict[str, float]:
        return {
            "loud_mic_rms": self.loud_mic_rms(),
            "silence_reset_rms": self.silence_reset_rms(),
            "phantom_min_peak_rms": self.phantom_min_peak_rms(),
            "partial_stability_s": self.partial_stability_s(),
            "stt_grace_after_silence_s": self.stt_grace_after_silence_s(),
            "partial_min_chars": float(self.partial_min_chars()),
            "final_transcript_timeout_s": self.final_transcript_timeout_s(),
            "max_asr_wait_after_end_s": self.max_asr_wait_after_end_s(),
        }

    def handbook_config(
        self,
        profile: PersonalityProfile | None = None,
    ) -> AgentHandbookConfig:
        """Agent Handbook presets — profile block overrides live_voice tone toggles."""
        if profile is not None:
            handbook = AgentHandbookConfig.from_profile(profile)
        else:
            handbook = AgentHandbookConfig(
                default_tone=self.default_tone,
                enable_natural_fillers=self.enable_natural_fillers,
                enable_high_empathy=self.enable_high_empathy,
            )
        return handbook

    def spoken_style_lines(
        self,
        *,
        language: str = "id",
        profile: PersonalityProfile | None = None,
    ) -> list[str]:
        """Retell Agent Handbook — Personality & Tone (+ linked presets)."""
        handbook = self.handbook_config(profile)
        return handbook.personality_tone_lines(language=language)

    def handbook_prompt_lines(
        self,
        *,
        language: str = "id",
        profile: PersonalityProfile | None = None,
    ) -> list[str]:
        """Full Agent Handbook prompt blocks (all enabled categories)."""
        handbook = self.handbook_config(profile)
        return handbook.prompt_lines(language=language)

    def pronunciation_lines(self) -> list[str]:
        if not self.pronunciations:
            return []
        lines = ["Pronunciation (say these exactly as guided):"]
        for entry in self.pronunciations:
            lines.append(f'- "{entry.word}" → {entry.guide}')
        return lines

    def should_emit_backchannel(self, transcript: str) -> bool:
        """Retell backchannel shows up on longer user utterances."""
        if not self.enable_backchannel or self.backchannel_frequency <= 0:
            return False
        words = len(transcript.split())
        min_words = max(6, int(round(20 - self.backchannel_frequency * 12)))
        return words >= min_words

    def with_client_overrides(
        self,
        *,
        voice_name: str | None = None,
        language_code: str | None = None,
    ) -> LiveVoiceConfig:
        kwargs: dict[str, str] = {}
        if voice_name:
            kwargs["voice_name"] = normalize_voice_name(voice_name)
        if language_code and isinstance(language_code, str) and language_code.strip():
            kwargs["language_code"] = language_code.strip()
        return replace(self, **kwargs) if kwargs else self

    def to_client_dict(self) -> dict[str, float | bool | str | int | None]:
        return {
            "responsiveness": self.responsiveness,
            "interruption_sensitivity": self.interruption_sensitivity,
            "enable_dynamic_responsiveness": self.enable_dynamic_responsiveness,
            "enable_backchannel": self.enable_backchannel,
            "backchannel_frequency": self.backchannel_frequency,
            "start_speaker": self.start_speaker,
            "speech_flexibility": self.speech_flexibility,
            "enable_speech_normalization": self.enable_speech_normalization,
            "denoising": self.denoising,
            "transcription_mode": self.transcription_mode,
            "boosted_keywords": list(self.boosted_keywords),
            "background_sound": self.background_sound,
            "default_tone": self.default_tone,
            "enable_natural_fillers": self.enable_natural_fillers,
            "enable_high_empathy": self.enable_high_empathy,
            "pronunciations": [
                {"word": p.word, "guide": p.guide} for p in self.pronunciations
            ],
            "barge_in_rms_threshold": self.barge_in_rms_threshold(),
            "barge_in_grace_ms": self.barge_in_grace_ms(),
            "barge_in_sustain_frames": self.barge_in_sustain_frames(),
            "barge_in_cooldown_ms": self.barge_in_cooldown_ms(),
            "smart_barge_min_ms": 800,
            "silence_duration_ms": self.silence_duration_ms(),
            "voice_name": self.voice_name,
            "language_code": self.language_code,
            "generation_temperature": self.generation_temperature,
        }

    @classmethod
    def from_profile(cls, profile: PersonalityProfile) -> LiveVoiceConfig:
        preset_id = profile.preset_id or "default_companion"
        try:
            raw = read_preset_json(preset_id)
        except (FileNotFoundError, OSError):
            return cls()
        block = raw.get("live_voice")
        if not isinstance(block, dict):
            return cls()
        return cls.from_dict(block)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LiveVoiceConfig:
        known = {
            "responsiveness",
            "interruption_sensitivity",
            "enable_dynamic_responsiveness",
            "enable_backchannel",
            "backchannel_frequency",
            "start_speaker",
            "begin_message",
            "begin_message_delay_ms",
            "speech_flexibility",
            "enable_speech_normalization",
            "denoising",
            "transcription_mode",
            "boosted_keywords",
            "background_sound",
            "default_tone",
            "enable_natural_fillers",
            "enable_high_empathy",
            "pronunciations",
            "voice_name",
            "language_code",
            "generation_temperature",
        }
        kwargs = {k: data[k] for k in known if k in data}
        if "boosted_keywords" in kwargs:
            raw_kw = kwargs.pop("boosted_keywords")
            if isinstance(raw_kw, list):
                kwargs["boosted_keywords"] = tuple(
                    str(item).strip() for item in raw_kw if str(item).strip()
                )
        if "pronunciations" in kwargs:
            raw = kwargs.pop("pronunciations")
            guides: list[PronunciationGuide] = []
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    word = str(item.get("word") or "").strip()
                    guide = str(
                        item.get("guide") or item.get("ipa") or item.get("cmu") or ""
                    ).strip()
                    if word and guide:
                        guides.append(PronunciationGuide(word=word, guide=guide))
            kwargs["pronunciations"] = tuple(guides)
        return cls(**kwargs)

    def opening_greeting_prompt(self, display_name: str) -> str | None:
        """No scripted opener — S2S uses system instruction only (avoids double greeting)."""
        return None

    def opening_or_resume_prompt(self, display_name: str, *, has_history: bool) -> str | None:
        """Greet only on a first meeting. An existing thread has no scripted opener."""
        if has_history:
            return None
        return self.opening_greeting_prompt(display_name)
