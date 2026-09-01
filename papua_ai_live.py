#!/usr/bin/env python3
"""
Papua AI — desktop Gemini Live demo (full-duplex voice + barge-in).

Uses the official google-genai Live API (same stack as persona_ai/web/gemini_live_bridge.py),
not raw WebSockets — the pasted wss:// URL in tutorials is easy to get wrong.

Install (new terminal):
    pip install google-genai pyaudio python-dotenv

Set API key (PowerShell):
    $env:GEMINI_API_KEY = "your-key-here"

Run:
    python papua_ai_live.py

Local RAG (optional):
    Edit database_papua.json (mop, lagu, budaya) — no Python changes needed.

Test:
    1. Wait for "Mikrofon aktif!" then say: "Halo pace, apa kabar?"
    2. While AI talks, interrupt: "Ah ko tipu!" — speaker should cut instantly.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Project imports (src/persona_ai)
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pyaudio
from google import genai
from google.genai import types

from persona_ai.env import load_project_dotenv
from persona_ai.llm.gemini_models import gemini_live_model
from persona_ai.personality.papua_local_database import (
    database_stats,
    load_papua_database,
    muat_pengetahuan_lokal,
    resolve_database_path,
)
from persona_ai.personality.preset import load_default_preset
from persona_ai.web.gemini_live_bridge import _activity_handling
from persona_ai.web.voice_config import LiveVoiceConfig
from persona_ai.web.voice_instruction import build_live_voice_instruction

# ── Audio (Gemini Live: mic 16 kHz in, speaker 24 kHz out) ─────────────────
INPUT_RATE = 16_000
OUTPUT_RATE = 24_000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 1024

DEFAULT_DIALECT = "papua"


def _build_instruction_with_rag() -> tuple[str, dict[str, int]]:
    """Gabung instruksi Persona + database lokal (RAG sederhana)."""
    profile = load_default_preset()
    instruction = build_live_voice_instruction(profile, dialect=DEFAULT_DIALECT)

    db_path = _ROOT / "database_papua.json"
    if not db_path.is_file():
        db_path = resolve_database_path()

    database_lokal = muat_pengetahuan_lokal(db_path)
    stats = database_stats(load_papua_database(db_path))
    if database_lokal:
        instruction = f"{instruction}{database_lokal}"
    return instruction, stats


def _resolve_api_key() -> str:
    load_project_dotenv()
    import os

    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        print(
            "❌ API key belum ada. Set GEMINI_API_KEY di .env atau environment.\n"
            "   PowerShell: $env:GEMINI_API_KEY = \"isi_api_key_gemini_di_sini\""
        )
        sys.exit(1)
    return key


def _live_connect_config(instruction: str, voice: LiveVoiceConfig) -> types.LiveConnectConfig:
    """Standalone demo: Gemini VAD ON so mic/speaker work without Persona governance."""
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        generation_config=types.GenerationConfig(temperature=voice.generation_temperature),
        input_audio_transcription=voice.input_transcription_config(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        speech_config=types.SpeechConfig(
            language_code=voice.language_code,
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice.voice_name)
            ),
        ),
        system_instruction=types.Content(parts=[types.Part(text=instruction)]),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=False),
            activity_handling=_activity_handling(voice),
        ),
    )


class AudioIO:
    """PyAudio mic + speaker with interrupt flush."""

    def __init__(self) -> None:
        self._pa = pyaudio.PyAudio()
        self.input = self._pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=INPUT_RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
        self.output = self._pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=OUTPUT_RATE,
            output=True,
            frames_per_buffer=CHUNK,
        )
        self._play_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._stop = asyncio.Event()

    def flush_output(self) -> None:
        """Cut AI speech immediately (barge-in)."""
        while True:
            try:
                self._play_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self.output.stop_stream()
        self.output.start_stream()

    async def read_mic_chunk(self) -> bytes:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.input.read(CHUNK, exception_on_overflow=False),
        )

    async def enqueue_playback(self, pcm: bytes) -> None:
        await self._play_queue.put(pcm)

    async def speaker_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            chunk = await self._play_queue.get()
            if chunk is None:
                break
            await loop.run_in_executor(None, self.output.write, chunk)

    def close(self) -> None:
        self._stop.set()
        for stream in (self.input, self.output):
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        self._pa.terminate()


async def kirim_audio_mikrofon(session: object, audio: AudioIO) -> None:
    print("🎤 Mikrofon aktif! Silakan bicara dengan Papua AI...")
    while True:
        pcm = await audio.read_mic_chunk()
        await session.send_realtime_input(  # type: ignore[attr-defined]
            audio=types.Blob(data=pcm, mime_type=f"audio/pcm;rate={INPUT_RATE}")
        )
        await asyncio.sleep(0.005)


async def terima_audio_dan_interupsi(session: object, audio: AudioIO) -> None:
    try:
        while True:
            msg = await session._receive()  # type: ignore[attr-defined]
            sc = getattr(msg, "server_content", None)
            if not sc:
                continue

            if sc.interrupted:
                print("\n⚠️ Ko potong pembicaraan! AI langsung diam...")
                audio.flush_output()
                continue

            if sc.input_transcription and sc.input_transcription.text:
                text = sc.input_transcription.text.strip()
                if text:
                    print(f"👂 Ko: {text}")

            if sc.output_transcription and sc.output_transcription.text:
                text = sc.output_transcription.text.strip()
                if text:
                    print(f"🤖 Papua AI: {text}")

            model_turn = sc.model_turn
            if not model_turn:
                continue
            for part in model_turn.parts or []:
                blob = part.inline_data
                if not blob or not blob.data:
                    continue
                mime = (blob.mime_type or "").lower()
                if mime.startswith("audio/pcm"):
                    await audio.enqueue_playback(blob.data)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"Error terima audio: {exc}")


async def main() -> None:
    api_key = _resolve_api_key()
    profile = load_default_preset()
    voice = LiveVoiceConfig.from_profile(profile)
    instruction, db_stats = _build_instruction_with_rag()
    model = gemini_live_model()
    config = _live_connect_config(instruction, voice)

    client = genai.Client(api_key=api_key)
    audio = AudioIO()
    speaker_task: asyncio.Task | None = None

    print(f"🔌 Menghubungkan ke Gemini Live ({model})...")
    if any(db_stats.values()):
        print(
            "📚 Database lokal dimuat — "
            f"{db_stats['mop_list']} mop, "
            f"{db_stats['lagu_list']} lagu, "
            f"{db_stats['budaya_list']} budaya"
        )
    else:
        print("ℹ️ database_papua.json kosong/tidak ada — lanjut tanpa RAG lokal.")
    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            print("✅ Terhubung!")
            print("🤖 Karakter Papua AI su aktif di dalam sistem!")
            print("   (Ctrl+C untuk keluar)\n")

            speaker_task = asyncio.create_task(audio.speaker_loop())
            await asyncio.gather(
                kirim_audio_mikrofon(session, audio),
                terima_audio_dan_interupsi(session, audio),
            )
    except KeyboardInterrupt:
        pass
    finally:
        if speaker_task is not None:
            await audio._play_queue.put(None)
            speaker_task.cancel()
            try:
                await speaker_task
            except asyncio.CancelledError:
                pass
        audio.close()
        print("\n👋 Program dimatikan. Terima kasih kaka!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Program dimatikan. Terima kasih kaka!")
