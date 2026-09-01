"""Gemini TTS — read-aloud for text chat responses."""

from __future__ import annotations

import logging
import re
import struct

from google import genai
from google.genai import types

from persona_ai.llm.gemini_models import gemini_tts_model
from persona_ai.web.voice_config import normalize_voice_name

_log = logging.getLogger(__name__)


def _tts_language_code(language_code: str | None) -> str | None:
    if not language_code:
        return None
    cleaned = language_code.strip()
    if not cleaned:
        return None
    # SpeechConfig expects ISO 639-1 (e.g. "id"), Live UI uses BCP-47 ("id-ID").
    return cleaned.split("-")[0].lower()


def _parse_pcm_rate(mime: str) -> int:
    match = re.search(r"rate=(\d+)", mime)
    return int(match.group(1)) if match else 24000


def _pcm16_to_wav(pcm: bytes, *, sample_rate: int, channels: int = 1) -> bytes:
    bits = 16
    block_align = channels * bits // 8
    byte_rate = sample_rate * block_align
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits,
        b"data",
        data_size,
    )
    return header + pcm


def _browser_audio(pcm_or_encoded: bytes, mime: str) -> tuple[bytes, str]:
    lower = mime.lower()
    if "pcm" in lower or "l16" in lower:
        rate = _parse_pcm_rate(mime)
        return _pcm16_to_wav(pcm_or_encoded, sample_rate=rate), "audio/wav"
    return pcm_or_encoded, mime or "audio/wav"


def synthesize_speech(
    client: genai.Client,
    text: str,
    *,
    voice_name: str,
    language_code: str | None = None,
) -> tuple[bytes, str]:
    """Return (audio_bytes, mime_type) for assistant text."""
    normalized = text.strip()
    if not normalized:
        raise ValueError("empty text")

    voice = normalize_voice_name(voice_name)
    lang = _tts_language_code(language_code)
    speech_cfg: dict = {
        "voice_config": types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
        ),
    }
    if lang:
        speech_cfg["language_code"] = lang

    response = client.models.generate_content(
        model=gemini_tts_model(),
        contents=normalized,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(**speech_cfg),
        ),
    )

    for candidate in response.candidates or []:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in content.parts or []:
            blob = part.inline_data
            if blob and blob.data:
                raw_mime = blob.mime_type or "audio/wav"
                audio_bytes, out_mime = _browser_audio(blob.data, raw_mime)
                _log.info(
                    "tts synthesized %s bytes voice=%s mime=%s",
                    len(audio_bytes),
                    voice,
                    out_mime,
                )
                return audio_bytes, out_mime

    raise RuntimeError("Gemini TTS returned no audio")
