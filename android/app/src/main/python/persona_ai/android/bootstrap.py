"""Start Persona AI HTTP server on-device for BYOK (Bring Your Own Key)."""

from __future__ import annotations

import os
import threading
import time

_server_thread: threading.Thread | None = None


def start_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    api_key: str = "",
    files_dir: str = "",
) -> bool:
    """Launch uvicorn in a daemon thread. Idempotent if already running."""
    global _server_thread
    if _server_thread is not None and _server_thread.is_alive():
        if api_key:
            os.environ["GEMINI_API_KEY"] = api_key
        return True

    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key
    os.environ["PERSONA_CHAT_HOST"] = host
    os.environ["PERSONA_DISABLE_SSL"] = "1"
    if files_dir:
        os.environ["PERSONA_SESSION_DB"] = os.path.join(files_dir, "persona_sessions.db")
        os.environ["PERSONA_MEMORY_DB"] = os.path.join(files_dir, "persona_user_memory.db")

    def _run() -> None:
        from persona_ai.android.asyncio_setup import ensure_event_loop, patch_uvicorn_for_embedded

        patch_uvicorn_for_embedded()
        ensure_event_loop()

        import uvicorn

        from persona_ai.web.server import app

        uvicorn.run(
            app,
            host=host,
            port=int(port),
            log_level="info",
            loop="asyncio",
        )

    _server_thread = threading.Thread(target=_run, daemon=True, name="persona-byok-http")
    _server_thread.start()
    return True


def wait_until_ready(host: str = "127.0.0.1", port: int = 8765, timeout_s: float = 45.0) -> bool:
    """Poll /api/health until server responds or timeout."""
    import urllib.error
    import urllib.request

    url = f"http://{host}:{port}/api/health"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.25)
    return False


def is_running() -> bool:
    return _server_thread is not None and _server_thread.is_alive()


def ambil_mop_acak() -> str:
    """Raja Mop — mop acak untuk Android/Kotlin bridge."""
    from persona_ai.personality.papua_mops import pick_random_mop

    return pick_random_mop()
