"""Tests for live voice tuning config."""

from __future__ import annotations

from persona_ai.core.types import PersonalityProfile
from persona_ai.web.voice_config import (
    RETELL_DEFAULT_BEGIN_MESSAGE,
    LiveVoiceConfig,
    PronunciationGuide,
    normalize_voice_name,
)


def test_silence_duration_matches_retell_wait_curve() -> None:
    fast = LiveVoiceConfig(responsiveness=1.0)
    slower = LiveVoiceConfig(responsiveness=0.9)
    slow = LiveVoiceConfig(responsiveness=0.0)
    assert fast.silence_duration_ms() == 200
    assert slower.silence_duration_ms() == 700  # -0.1 → +500ms
    assert slow.silence_duration_ms() == 5200
    assert fast.silence_duration_ms() < slower.silence_duration_ms() < slow.silence_duration_ms()


def test_barge_in_waits_for_real_speech() -> None:
    cfg = LiveVoiceConfig()
    assert cfg.barge_in_grace_ms() == 280
    assert cfg.barge_in_sustain_frames() == 36
    assert cfg.barge_in_cooldown_ms() == 450
    assert cfg.prefix_padding_ms() == 120
    assert cfg.barge_in_rms_threshold() == 0.05
    stiff = LiveVoiceConfig(interruption_sensitivity=0.0)
    assert stiff.barge_in_grace_ms() > cfg.barge_in_grace_ms()
    assert stiff.prefix_padding_ms() > cfg.prefix_padding_ms()
    assert stiff.barge_in_rms_threshold() > cfg.barge_in_rms_threshold()


def test_barge_threshold_scales_with_interruption_sensitivity() -> None:
    sensitive = LiveVoiceConfig(interruption_sensitivity=1.0)
    stiff = LiveVoiceConfig(interruption_sensitivity=0.0)
    assert sensitive.barge_in_rms_threshold() < stiff.barge_in_rms_threshold()
    assert sensitive.barge_in_rms_threshold() == 0.05
    assert stiff.barge_in_rms_threshold() == 0.10


def test_backchannel_only_on_longer_utterances() -> None:
    cfg = LiveVoiceConfig(enable_backchannel=True, backchannel_frequency=0.8)
    assert not cfg.should_emit_backchannel("Halo.")
    assert not cfg.should_emit_backchannel("Iya tadi pagi aku ke pasar")
    long = "Tadi pagi aku ke pasar beli sayur buah beras dan pulang agak sore"
    assert cfg.should_emit_backchannel(long)
    off = LiveVoiceConfig(enable_backchannel=False)
    assert not off.should_emit_backchannel(long)


def test_opening_greeting_agent_only() -> None:
    cfg = LiveVoiceConfig(start_speaker="agent")
    prompt = cfg.opening_greeting_prompt("Persona")
    assert RETELL_DEFAULT_BEGIN_MESSAGE is None
    assert prompt is not None
    assert "Sapa user singkat dan natural" in prompt
    user_first = LiveVoiceConfig(start_speaker="user")
    assert user_first.opening_greeting_prompt("Persona") is None


def test_resume_prompt_skips_fresh_greeting() -> None:
    cfg = LiveVoiceConfig(start_speaker="agent")
    fresh = cfg.opening_or_resume_prompt("Persona", has_history=False)
    resume = cfg.opening_or_resume_prompt("Persona", has_history=True)
    assert fresh is not None
    assert "Sapa user singkat dan natural" in fresh
    assert resume is None
    user_first = LiveVoiceConfig(start_speaker="user")
    assert user_first.opening_or_resume_prompt("Persona", has_history=True) is None


def test_from_profile_reads_preset_live_voice() -> None:
    profile = PersonalityProfile(id="t", preset_id="default_companion", display_name="Persona")
    cfg = LiveVoiceConfig.from_profile(profile)
    assert cfg.responsiveness == 1.0
    assert cfg.interruption_sensitivity == 1.0
    assert cfg.enable_dynamic_responsiveness is True
    assert cfg.enable_backchannel is True
    assert cfg.backchannel_frequency == 0.8
    assert cfg.begin_message_delay_ms == 1000
    assert cfg.begin_message is None
    assert cfg.speech_flexibility == 0.65
    assert cfg.denoising == "remove_noise_and_background_speech"
    assert cfg.transcription_mode == "custom"
    assert "tra" in cfg.boosted_keywords
    assert cfg.default_tone == "companion_friend"
    assert cfg.enable_natural_fillers is True
    assert cfg.enable_high_empathy is True
    assert cfg.voice_name == "Leda"
    assert cfg.language_code == "id-ID"
    assert cfg.generation_temperature == 0.65


def test_defaults_match_retell_agent_dashboard() -> None:
    cfg = LiveVoiceConfig()
    assert cfg.responsiveness == 1.0
    assert cfg.interruption_sensitivity == 1.0
    assert cfg.enable_dynamic_responsiveness is True
    assert cfg.background_sound is None
    assert cfg.begin_message_delay_ms == 1000
    assert cfg.begin_message is None
    assert cfg.silence_duration_ms() == 200
    assert cfg.loud_mic_rms() == 0.05
    assert abs(cfg.partial_stability_s() - 0.12) < 0.001
    assert abs(cfg.stt_grace_after_silence_s() - 0.18) < 0.001
    assert cfg.default_tone == "professional_conversational"


def test_dynamic_responsiveness_adjusts_eagerness() -> None:
    cfg = LiveVoiceConfig(responsiveness=1.0, enable_dynamic_responsiveness=True)
    assert cfg.effective_responsiveness(transcript="Oke.") >= 1.0
    assert cfg.effective_responsiveness(transcript="Hmm jadi gimana ya", voice_pause_ms=1500) < 1.0
    static = LiveVoiceConfig(responsiveness=0.9, enable_dynamic_responsiveness=False)
    assert static.effective_responsiveness(transcript="Oke.", voice_pause_ms=2000) == 0.9


def test_pronunciation_lines_and_preset_parse() -> None:
    cfg = LiveVoiceConfig(
        pronunciations=(PronunciationGuide(word="Persona", guide="peh-ROH-nah"),)
    )
    lines = cfg.pronunciation_lines()
    assert any("Persona" in line for line in lines)
    parsed = LiveVoiceConfig.from_dict(
        {"pronunciations": [{"word": "AI", "guide": "/eɪ aɪ/"}]}
    )
    assert parsed.pronunciations[0].word == "AI"


def test_retell_speech_flexibility_derived_timings() -> None:
    flexible = LiveVoiceConfig(speech_flexibility=0.8, transcription_mode="custom")
    strict = LiveVoiceConfig(speech_flexibility=0.2, transcription_mode="custom")
    assert flexible.partial_stability_s() < strict.partial_stability_s()
    assert flexible.stt_grace_after_silence_s() < strict.stt_grace_after_silence_s()


def test_transcription_mode_speed_vs_accuracy() -> None:
    speed = LiveVoiceConfig(transcription_mode="speed")
    accuracy = LiveVoiceConfig(transcription_mode="accuracy")
    custom = LiveVoiceConfig(transcription_mode="custom", speech_flexibility=0.8)
    assert speed.partial_min_chars() < accuracy.partial_min_chars()
    assert speed.final_transcript_timeout_s() < accuracy.final_transcript_timeout_s()
    assert speed.max_asr_wait_after_end_s() < accuracy.max_asr_wait_after_end_s()
    assert custom.partial_min_chars() == 6
    assert speed.effective_speech_flexibility() == 1.0
    assert accuracy.effective_speech_flexibility() == 0.2


def test_boosted_keywords_in_transcription_config() -> None:
    cfg = LiveVoiceConfig(boosted_keywords=("Persona", "Retell"))
    asr = cfg.input_transcription_config()
    assert asr.custom_vocabulary == ["Persona", "Retell"]
    hints = cfg.transcription_hint_lines()
    assert any("Persona" in line for line in hints)


def test_denoising_modes_adjust_mic_thresholds() -> None:
    aggressive = LiveVoiceConfig(denoising="remove_noise_and_background_speech")
    light = LiveVoiceConfig(denoising="remove_noise")
    off = LiveVoiceConfig(denoising="none")
    assert aggressive.loud_mic_rms() > off.loud_mic_rms()
    assert light.loud_mic_rms() > off.loud_mic_rms()


def test_normalize_voice_name_fallback() -> None:
    assert normalize_voice_name("invalid") == "Leda"
    assert normalize_voice_name("leda") == "Leda"


def test_spoken_style_lines_retell_tone() -> None:
    cfg = LiveVoiceConfig(
        default_tone="professional_conversational",
        enable_natural_fillers=True,
        enable_high_empathy=True,
    )
    lines = cfg.spoken_style_lines(language="id")
    assert any("conversational" in line.lower() for line in lines)
    assert any("filler" in line.lower() for line in lines)
    assert any("frustrasi" in line.lower() for line in lines)

    minimal = LiveVoiceConfig(
        default_tone="professional",
        enable_natural_fillers=False,
        enable_high_empathy=False,
    )
    minimal_lines = minimal.spoken_style_lines()
    assert len(minimal_lines) == 1
    assert "profesional" in minimal_lines[0].lower()


def test_with_client_overrides() -> None:
    cfg = LiveVoiceConfig()
    updated = cfg.with_client_overrides(voice_name="Aoede", language_code="en-US")
    assert updated.voice_name == "Aoede"
    assert updated.language_code == "en-US"
