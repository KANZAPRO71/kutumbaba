#!/usr/bin/env python3
"""
Papua AI — desktop GUI (tkinter) untuk Gemini Live full-duplex + barge-in.

Install:
    pip install google-genai pyaudio python-dotenv

API key (.env atau environment):
    GEMINI_API_KEY=your-key-here

Jalankan (double-click atau terminal):
    python papua_ai_gui.py

tkinter sudah bawaan Python di Windows — tra perlu pip install terpisah.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

# Project imports (src/persona_ai)
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from google import genai
from google.genai import types

from persona_ai.env import load_project_dotenv
from persona_ai.llm.gemini_models import gemini_live_model
from persona_ai.personality.preset import load_default_preset
from persona_ai.web.voice_config import LiveVoiceConfig

# Reuse audio + Live helpers from CLI demo
from papua_ai_live import (  # noqa: E402 — after sys.path
    INPUT_RATE,
    AudioIO,
    _build_instruction_with_rag,
    _live_connect_config,
)

# ── Tema UI ─────────────────────────────────────────────────────────────────
BG = "#1e1e1e"
PANEL = "#2d2d2d"
ACCENT = "#00ffcc"
TEXT = "#ffffff"

STATUS = {
    "off": ("Status: OFF / MATI", "#ff3333", "●"),
    "connecting": ("Status: MENGHUBUNGKAN...", "#ff9900", "●"),
    "ready": ("Status: AKTIF — siap dengar ko", "#00ff00", "●"),
    "listening": ("Status: 🎤 KO BICARA (mendengarkan...)", "#00ccff", "●"),
    "speaking": ("Status: 🤖 AI BICARA", "#cc66ff", "●"),
}


def _get_api_key() -> str | None:
    load_project_dotenv()
    import os

    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    return key or None


class PapuaAIGUI:
    """Jendela Papua AI — Start/Stop, log, indikator dengar/bicara."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("PAPUA AI — Full Duplex Client")
        self.root.geometry("480x420")
        self.root.configure(bg=BG)
        self.root.minsize(420, 380)

        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = asyncio.Event()
        self._thread: threading.Thread | None = None
        self._session_cm = None
        self._session = None
        self._audio: AudioIO | None = None
        self._tasks: list[asyncio.Task] = []

        self._setup_ui()
        self._set_status("off")

    def _setup_ui(self) -> None:
        title = tk.Label(
            self.root,
            text="PAPUA AI INTERAKTIF",
            font=("Segoe UI", 16, "bold"),
            fg=ACCENT,
            bg=BG,
        )
        title.pack(pady=(18, 6))

        subtitle = tk.Label(
            self.root,
            text="Gemini Live · Melayu Papua · Barge-in",
            font=("Segoe UI", 9),
            fg="#888888",
            bg=BG,
        )
        subtitle.pack(pady=(0, 10))

        indicator_frame = tk.Frame(self.root, bg=BG)
        indicator_frame.pack(pady=4)

        self._indicator = tk.Label(
            indicator_frame,
            text="●",
            font=("Segoe UI", 22),
            fg="#ff3333",
            bg=BG,
        )
        self._indicator.pack(side=tk.LEFT, padx=(0, 8))

        self._status_label = tk.Label(
            indicator_frame,
            text="Status: OFF / MATI",
            font=("Segoe UI", 11),
            fg="#ff3333",
            bg=BG,
        )
        self._status_label.pack(side=tk.LEFT)

        log_frame = tk.Frame(self.root, bg=BG)
        log_frame.pack(pady=12, padx=16, fill=tk.BOTH, expand=True)

        self._log = tk.Text(
            log_frame,
            height=8,
            width=52,
            bg=PANEL,
            fg=TEXT,
            font=("Consolas", 10),
            wrap=tk.WORD,
            relief=tk.FLAT,
            padx=8,
            pady=8,
        )
        scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self._log.yview)
        self._log.configure(yscrollcommand=scroll.set)
        self._log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._write_log("Aplikasi siap. Set GEMINI_API_KEY di .env lalu klik KASI MENYALA.")

        btn_frame = tk.Frame(self.root, bg=BG)
        btn_frame.pack(pady=(4, 18))

        self._start_btn = tk.Button(
            btn_frame,
            text="▶  KASI MENYALA",
            font=("Segoe UI", 11, "bold"),
            bg="#00cc66",
            fg="white",
            activebackground="#00aa55",
            activeforeground="white",
            width=16,
            relief=tk.FLAT,
            padx=4,
            pady=6,
            command=self.start_ai,
        )
        self._start_btn.grid(row=0, column=0, padx=8)

        self._stop_btn = tk.Button(
            btn_frame,
            text="⏹  KASI MATI",
            font=("Segoe UI", 11, "bold"),
            bg="#cc3333",
            fg="white",
            activebackground="#aa2222",
            activeforeground="white",
            width=16,
            relief=tk.FLAT,
            padx=4,
            pady=6,
            command=self.stop_ai,
            state=tk.DISABLED,
        )
        self._stop_btn.grid(row=0, column=1, padx=8)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_status(self, key: str) -> None:
        label, color, dot = STATUS.get(key, STATUS["off"])
        self._status_label.config(text=label, fg=color)
        self._indicator.config(fg=color, text=dot)

    def _write_log(self, text: str) -> None:
        self._log.insert(tk.END, text + "\n")
        self._log.see(tk.END)

    def _ui(self, fn) -> None:
        """Jalankan callback di thread utama Tk."""
        self.root.after(0, fn)

    def _ui_log(self, text: str) -> None:
        self._ui(lambda: self._write_log(text))

    def _ui_status(self, key: str) -> None:
        self._ui(lambda: self._set_status(key))

    def start_ai(self) -> None:
        if self._running:
            return
        if not _get_api_key():
            messagebox.showerror(
                "API Key belum ada",
                "Set GEMINI_API_KEY di file .env atau environment variable.\n\n"
                "PowerShell:\n  $env:GEMINI_API_KEY = \"isi_api_key_gemini_di_sini\"",
            )
            return

        self._running = True
        self._stop = asyncio.Event()
        self._start_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.NORMAL)
        self._set_status("connecting")
        self._write_log("Menghubungkan ke Gemini Live...")

        self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._thread.start()

    def stop_ai(self) -> None:
        if not self._running:
            return
        self._running = False
        self._write_log("Mematikan sistem...")
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)

    def _run_async_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._live_session())
        except Exception as exc:
            self._ui_log(f"Error: {exc}")
        finally:
            self._loop.close()
            self._loop = None
            self._ui(self._on_stopped)

    def _on_stopped(self) -> None:
        self._running = False
        self._set_status("off")
        self._start_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)
        self._write_log("Sistem dimatikan.")

    def _on_close(self) -> None:
        if self._running:
            self.stop_ai()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=3.0)
        self.root.destroy()

    async def _shutdown(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        if self._audio is not None:
            try:
                await self._audio._play_queue.put(None)
            except Exception:
                pass
        if self._session_cm is not None:
            try:
                await self._session_cm.__aexit__(None, None, None)
            except Exception:
                pass
        if self._audio is not None:
            self._audio.close()
            self._audio = None

    async def _send_mic(self, session: object) -> None:
        assert self._audio is not None
        self._ui_log("Mikrofon aktif! Silakan bicara dengan Papua AI...")
        self._ui_status("ready")
        while not self._stop.is_set():
            pcm = await self._audio.read_mic_chunk()
            if self._stop.is_set():
                break
            await session.send_realtime_input(  # type: ignore[attr-defined]
                audio=types.Blob(data=pcm, mime_type=f"audio/pcm;rate={INPUT_RATE}")
            )
            await asyncio.sleep(0.005)

    async def _recv_audio(self, session: object) -> None:
        assert self._audio is not None
        while not self._stop.is_set():
            try:
                msg = await asyncio.wait_for(session._receive(), timeout=0.35)  # type: ignore[attr-defined]
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._stop.is_set():
                    break
                continue

            sc = getattr(msg, "server_content", None)
            if not sc:
                continue

            if sc.interrupted:
                self._ui_log("Ko potong pembicaraan! AI langsung diam...")
                self._audio.flush_output()
                self._ui_status("listening")
                continue

            if sc.input_transcription and sc.input_transcription.text:
                text = sc.input_transcription.text.strip()
                if text:
                    self._ui_log(f"Ko: {text}")
                    self._ui_status("listening")

            if sc.output_transcription and sc.output_transcription.text:
                text = sc.output_transcription.text.strip()
                if text:
                    self._ui_log(f"Papua AI: {text}")

            model_turn = sc.model_turn
            if not model_turn:
                continue
            for part in model_turn.parts or []:
                blob = part.inline_data
                if not blob or not blob.data:
                    continue
                mime = (blob.mime_type or "").lower()
                if mime.startswith("audio/pcm"):
                    self._ui_status("speaking")
                    await self._audio.enqueue_playback(blob.data)

    async def _speaker_loop(self) -> None:
        assert self._audio is not None
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                chunk = await asyncio.wait_for(self._audio._play_queue.get(), timeout=0.35)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            if chunk is None or self._stop.is_set():
                break
            await loop.run_in_executor(None, self._audio.output.write, chunk)

    async def _live_session(self) -> None:
        api_key = _get_api_key()
        if not api_key:
            return

        profile = load_default_preset()
        voice = LiveVoiceConfig.from_profile(profile)
        instruction, db_stats = _build_instruction_with_rag()
        model = gemini_live_model()
        config = _live_connect_config(instruction, voice)
        client = genai.Client(api_key=api_key)

        if any(db_stats.values()):
            self._ui_log(
                f"Database lokal: {db_stats['mop_list']} mop, "
                f"{db_stats['lagu_list']} lagu, {db_stats['budaya_list']} budaya"
            )

        self._audio = AudioIO()
        connect_cm = client.aio.live.connect(model=model, config=config)
        self._session_cm = connect_cm
        session = await connect_cm.__aenter__()
        self._session = session

        self._ui_log(f"Terhubung ke Gemini Live ({model})!")
        self._ui_log("Karakter Papua AI su aktif!")
        self._ui_status("ready")

        self._tasks = [
            asyncio.create_task(self._send_mic(session)),
            asyncio.create_task(self._recv_audio(session)),
            asyncio.create_task(self._speaker_loop()),
        ]
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            pass
        finally:
            for task in self._tasks:
                if not task.done():
                    task.cancel()
            if self._session_cm is not None:
                try:
                    await self._session_cm.__aexit__(None, None, None)
                except Exception:
                    pass
                self._session_cm = None
            if self._audio is not None:
                self._audio.close()
                self._audio = None


def main() -> None:
    root = tk.Tk()
    PapuaAIGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
