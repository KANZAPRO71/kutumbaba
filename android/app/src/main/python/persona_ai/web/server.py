"""Persona Chat — web UI + PersonaRuntime API + Gemini Live voice."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from google import genai

from persona_ai import PersonaRuntime
from persona_ai.env import load_project_dotenv
from persona_ai.integrations.retell_webhook import RetellPersonaBridge
from persona_ai.llm.adapter import LLMAdapter
from persona_ai.llm.gemini import GeminiLLMAdapter
from persona_ai.llm.gemini_models import (
    gemini_live_model,
    gemini_post_call_model,
    gemini_text_model,
    gemini_tts_model,
)
from persona_ai.llm.prompt import looks_like_current_time_question
from persona_ai.web.time_awareness import TimeAwarenessConfig
from persona_ai.personality.preset import load_preset_by_id
from persona_ai.personality.papua_mops import (
    classic_mop_count,
    mop_count,
    pick_random_mop,
    preview_mops,
    usage_note as mop_usage_note,
)
from persona_ai.personality.papua_music import catalog_count, preview_songs, song_count, topic_count, usage_note as music_usage_note
from persona_ai.personality.papua_kamus import entry_count, preview_entries, usage_note as kamus_usage_note
from persona_ai.personality.papua_live_system_instruction import master_system_instruction_text
from persona_ai.personality.papua_developer_credit import (
    developer_name,
    developer_role,
    ui_credit_line,
)
from persona_ai.web.gemini_live_bridge import _is_phantom_asr_phrase, handle_live_websocket
from persona_ai.web.gemini_tts import synthesize_speech
from persona_ai.web.persona_live import LIVE_RESPONSE_POLICY
from persona_ai.web.dynamic_variables import merge_dynamic_variables
from persona_ai.web.security_config import LiveSecurityConfig
from persona_ai.web.voice_config import LiveVoiceConfig, list_live_voices, normalize_voice_name
from persona_ai.web.webhook_config import LiveWebhookConfig
from persona_ai.web.webhook_delivery import deliver_webhook_event, sample_test_call
from persona_ai.memory.engine import (
    add_memory,
    commit_from_text,
    delete_memory,
    list_memories,
    memory_storage_path,
    memory_summary_for_client,
)
from persona_ai.session.store import SQLiteSessionStore, default_db_path

load_project_dotenv()

_log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

_runtime: PersonaRuntime | None = None
_adapter: LLMAdapter | None = None
_llm_kind: str = "gemini"
_retell_bridge: RetellPersonaBridge | None = None
_runtime_error: str | None = None
_session_store: SQLiteSessionStore | None = None


def _preset_id() -> str:
    return os.environ.get("PERSONA_PRESET", "default_companion")


def _get_session_store() -> SQLiteSessionStore:
    """Session history must load even when Gemini runtime is not ready."""
    global _session_store
    if _runtime is not None:
        store = _runtime.session_store
        if isinstance(store, SQLiteSessionStore):
            return store
    if _session_store is None:
        _session_store = SQLiteSessionStore(default_db_path())
    return _session_store


def _load_session_or_empty(session_id: str):
    try:
        return _get_session_store().load(session_id)
    except Exception:
        _log.exception("failed to load session %s", session_id)
        return None


def _build_runtime() -> tuple[PersonaRuntime, LLMAdapter, str]:
    adapter = GeminiLLMAdapter()
    profile = load_preset_by_id(_preset_id())
    security_cfg = LiveSecurityConfig.from_profile(profile)
    runtime = PersonaRuntime(
        session_store=_get_session_store(),
        llm_adapter=adapter,
        personality_profile=profile,
    )
    runtime.configure_live_security(security_cfg)
    return runtime, adapter, "gemini"


def _ensure_runtime() -> tuple[PersonaRuntime, LLMAdapter, str]:
    global _runtime, _adapter, _llm_kind, _runtime_error, _retell_bridge
    if _runtime is not None and _adapter is not None:
        return _runtime, _adapter, _llm_kind
    try:
        _runtime, _adapter, _llm_kind = _build_runtime()
        _runtime_error = None
        _retell_bridge = RetellPersonaBridge(runtime=_runtime)
    except Exception as exc:
        _runtime_error = str(exc)
        _log.exception("runtime init failed")
        raise HTTPException(status_code=503, detail=_runtime_error) from exc
    return _runtime, _adapter, _llm_kind


def _retell() -> RetellPersonaBridge:
    _ensure_runtime()
    assert _retell_bridge is not None
    return _retell_bridge


app = FastAPI(title="Papua AI", version="2.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    text: str | None
    bdv: str | None
    raw_bdv: str | None = None
    effective_bdv: str | None = None
    llm_called: bool
    execution_profile: str | None = None
    pre_llm_ms: float | None = None


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    voice_name: str | None = None
    language_code: str | None = None


class TtsResponse(BaseModel):
    mime: str
    data: str  # base64 audio


class RetellTurnRequest(BaseModel):
    session_id: str | None = None
    call_id: str | None = None
    transcript: str | None = None
    user_message: str | None = None
    voice_pause_ms: int | None = None


class ByokRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)


class MemoryCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    memory_type: str = Field(default="manual", max_length=32)


class MemoryDeleteResponse(BaseModel):
    ok: bool
    id: str


def _reset_runtime() -> None:
    global _runtime, _adapter, _llm_kind, _runtime_error, _retell_bridge
    _runtime = None
    _adapter = None
    _retell_bridge = None
    _runtime_error = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.get("/api/health")
def health() -> dict:
    if _runtime is None:
        profile = load_preset_by_id(_preset_id())
        voice_cfg = LiveVoiceConfig.from_profile(profile)
        security_cfg = LiveSecurityConfig.from_profile(profile)
        webhook_cfg = LiveWebhookConfig.from_profile(profile)
        api_key = os.environ.get("GEMINI_API_KEY", "")
        return {
            "status": "degraded" if not api_key else "starting",
            "persona_name": profile.display_name,
            "preset_id": profile.preset_id or _preset_id(),
            "connected": bool(api_key),
            "llm": _llm_kind,
            "text_model": gemini_text_model(),
            "live_model": gemini_live_model(),
            "tts_model": gemini_tts_model(),
            "post_call_model": gemini_post_call_model(),
            "gemini_key_set": bool(api_key),
            "voice_provider": "gemini_live",
            "live_voices": list_live_voices(),
            "default_voice": voice_cfg.voice_name,
            "default_language": voice_cfg.language_code,
            "security_config": security_cfg.to_client_dict(),
            "webhook_config": webhook_cfg.to_client_dict(),
            "developer_name": developer_name(),
            "developer_role": developer_role(),
            "developer_credit": ui_credit_line(),
            "live_web_search": True,
            "error": _runtime_error,
        }

    runtime, adapter, llm_kind = _ensure_runtime()
    profile = runtime.personality_profile
    voice_cfg = LiveVoiceConfig.from_profile(profile)
    security_cfg = LiveSecurityConfig.from_profile(profile)
    webhook_cfg = LiveWebhookConfig.from_profile(profile)
    return {
        "status": "ok",
        "persona_name": profile.display_name,
        "preset_id": profile.preset_id or _preset_id(),
        "connected": bool(getattr(adapter, "api_key", "")),
        "llm": llm_kind,
        "text_model": gemini_text_model(),
        "live_model": gemini_live_model(),
        "tts_model": gemini_tts_model(),
        "post_call_model": gemini_post_call_model(),
        "gemini_key_set": bool(getattr(adapter, "api_key", "")),
        "voice_provider": "gemini_live",
        "live_voices": list_live_voices(),
        "default_voice": voice_cfg.voice_name,
        "default_language": voice_cfg.language_code,
        "security_config": security_cfg.to_client_dict(),
        "webhook_config": webhook_cfg.to_client_dict(),
        "developer_name": developer_name(),
        "developer_role": developer_role(),
        "developer_credit": ui_credit_line(),
        "live_web_search": True,
    }


@app.post("/api/byok")
def configure_byok(body: ByokRequest) -> dict:
    """BYOK — set Gemini API key at runtime (mobile / self-hosted)."""
    key = body.api_key.strip()
    os.environ["GEMINI_API_KEY"] = key
    _reset_runtime()
    return {"ok": True, "gemini_key_set": bool(key)}


@app.get("/api/byok/status")
def byok_status() -> dict:
    key = os.environ.get("GEMINI_API_KEY", "")
    return {"configured": bool(key), "gemini_key_set": bool(key)}


@app.get("/api/papua/mops")
def papua_mops_catalog() -> dict:
    """Katalog Mop Papua — lelucon verbal untuk UI & debugging."""
    return {
        "count": mop_count(),
        "classic_count": classic_mop_count(),
        "usage_note": mop_usage_note(),
        "preview": preview_mops(10),
    }


@app.get("/api/papua/mop/random")
def papua_mop_random() -> dict:
    """Raja Mop — satu mop acak (anti-ulang dalam sesi)."""
    text = pick_random_mop()
    return {"text": text, "classic_count": classic_mop_count()}


@app.get("/api/papua/music")
def papua_music_catalog() -> dict:
    """Katalog lagu & musik Papua."""
    return {
        "song_count": song_count(),
        "topic_count": topic_count(),
        "catalog_count": catalog_count(),
        "usage_note": music_usage_note(),
        "preview": preview_songs(10),
    }


@app.get("/api/papua/kamus")
def papua_kamus_catalog() -> dict:
    """Kamus Bahasa Papua — preview untuk UI & debugging."""
    return {
        "count": entry_count(),
        "usage_note": kamus_usage_note(),
        "preview": preview_entries(10),
    }


@app.get("/api/papua/system-instruction")
def papua_system_instruction() -> dict:
    """Master System Instruction siap copy-paste ke Gemini Live."""
    runtime, _, _ = _ensure_runtime()
    name = runtime.personality_profile.display_name or "Papua AI"
    text = master_system_instruction_text("papua", display_name=name)
    return {
        "display_name": name,
        "dialect": "papua",
        "text": text,
        "note": "Teks ini otomatis disuntik ke Gemini Live saat dialect=papua. Bisa copy untuk debugging.",
    }


def _session_messages_for_client(session) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for msg in session.messages[-40:]:
        text = msg.text or ""
        if msg.role == "user" and _is_phantom_asr_phrase(text):
            continue
        messages.append({"role": msg.role, "text": text})
    return messages


@app.get("/api/sessions/latest")
def latest_session() -> dict:
    """Return the most recent session only when explicitly requested (no auto-resume)."""
    try:
        latest = getattr(_get_session_store(), "latest_with_messages", None)
        session = latest() if callable(latest) else None
    except Exception:
        _log.exception("failed to load latest session")
        session = None
    if session is None:
        return {"session_id": None, "messages": []}
    return {
        "session_id": session.session_id,
        "messages": _session_messages_for_client(session),
        "post_call": session.post_call,
    }


@app.get("/api/session/{session_id}/post-call")
def get_session_post_call(session_id: str) -> dict:
    if not session_id or len(session_id) > 128:
        raise HTTPException(status_code=400, detail="invalid session_id")
    session = _load_session_or_empty(session_id)
    if session is None or not session.post_call:
        return {"session_id": session_id, "post_call": None}
    return {"session_id": session_id, "post_call": session.post_call}


@app.get("/api/session/{session_id}")
def get_session(session_id: str) -> dict:
    if not session_id or len(session_id) > 128:
        raise HTTPException(status_code=400, detail="invalid session_id")
    session = _load_session_or_empty(session_id)
    if session is None:
        return {"session_id": session_id, "messages": [], "post_call": None}
    return {
        "session_id": session.session_id,
        "messages": _session_messages_for_client(session),
        "post_call": session.post_call,
    }


@app.get("/api/memory")
def get_user_memory() -> dict:
    """List facts stored locally on the user's device."""
    records = list_memories()
    return {
        "count": len(records),
        "storage_path": memory_storage_path(),
        "memories": memory_summary_for_client(records),
    }


@app.post("/api/memory")
def create_user_memory(body: MemoryCreateRequest) -> dict:
    memory_type = body.memory_type if body.memory_type in {
        "semantic", "preference", "episodic", "manual"
    } else "manual"
    record = add_memory(body.content.strip(), memory_type=memory_type, source="manual")
    if record is None:
        raise HTTPException(status_code=400, detail="content too short")
    return {"ok": True, "memory": memory_summary_for_client([record])[0]}


@app.delete("/api/memory/{memory_id}", response_model=MemoryDeleteResponse)
def remove_user_memory(memory_id: str) -> MemoryDeleteResponse:
    if not memory_id or len(memory_id) > 64:
        raise HTTPException(status_code=400, detail="invalid memory_id")
    ok = delete_memory(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="memory not found")
    return MemoryDeleteResponse(ok=True, id=memory_id)


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    runtime, _, _ = _ensure_runtime()
    profile = runtime.personality_profile
    time_cfg = TimeAwarenessConfig.from_profile(profile)
    lang = profile.default_language or "id"

    if looks_like_current_time_question(body.message):
        return ChatResponse(
            text=time_cfg.time_answer(language=lang),
            bdv="RESPOND",
            raw_bdv="RESPOND",
            effective_bdv="RESPOND",
            llm_called=False,
            execution_profile="clock",
            pre_llm_ms=0.0,
        )

    try:
        out = runtime.process_turn(
            body.session_id,
            body.message,
            channel="text",
            response_policy=LIVE_RESPONSE_POLICY,
        )
        commit_from_text(body.message, session_id=body.session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    profile = out.trace.execution_profile if out.trace else None
    pre_llm = out.trace.timing.pre_llm_ms if out.trace and out.trace.timing else None

    return ChatResponse(
        text=out.text,
        bdv=out.bdv.speak.value if out.bdv else None,
        raw_bdv=out.raw_bdv.speak.value if out.raw_bdv else None,
        effective_bdv=out.effective_bdv.speak.value if out.effective_bdv else None,
        llm_called=out.llm_called,
        execution_profile=profile,
        pre_llm_ms=pre_llm,
    )


@app.post("/api/tts", response_model=TtsResponse)
def tts(body: TtsRequest) -> TtsResponse:
    """Synthesize assistant text for chat read-aloud (Gemini TTS)."""
    import base64

    _, adapter, _ = _ensure_runtime()
    api_key = getattr(adapter, "api_key", "") or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY tidak diset")

    runtime, _, _ = _ensure_runtime()
    voice_cfg = LiveVoiceConfig.from_profile(runtime.personality_profile)
    voice_name = normalize_voice_name(body.voice_name or voice_cfg.voice_name)
    language_code = body.language_code or voice_cfg.language_code

    try:
        client = genai.Client(api_key=api_key)
        audio_bytes, mime = synthesize_speech(
            client,
            body.text,
            voice_name=voice_name,
            language_code=language_code,
        )
    except Exception as exc:
        detail = str(exc)
        if "429" in detail or "Too Many Requests" in detail or "RESOURCE_EXHAUSTED" in detail:
            raise HTTPException(
                status_code=429,
                detail="TTS rate limit Gemini — coba lagi sebentar atau matikan read-aloud.",
            ) from exc
        raise HTTPException(status_code=502, detail=f"TTS gagal: {exc}") from exc

    return TtsResponse(
        mime=mime,
        data=base64.b64encode(audio_bytes).decode("ascii"),
    )


@app.post("/api/webhook/test")
def webhook_test() -> dict[str, Any]:
    """Retell dashboard Test button — POST sample call_started to agent webhook URL."""
    profile = load_preset_by_id(_preset_id())
    webhook_cfg = LiveWebhookConfig.from_profile(profile)
    if not webhook_cfg.enabled:
        raise HTTPException(status_code=400, detail="webhook_url belum dikonfigurasi di live_webhook preset")
    security_cfg = LiveSecurityConfig.from_profile(profile)
    dyn_vars = merge_dynamic_variables(
        security_cfg.default_dynamic_variables,
        {"agent_name": profile.display_name},
    )
    call = sample_test_call(agent_id=profile.preset_id or _preset_id())
    result = deliver_webhook_event(
        webhook_cfg,
        event="call_started",
        call=call,
        dynamic_variables=dyn_vars,
    )
    if not result.get("ok"):
        detail = result.get("error") or result.get("reason") or "webhook test gagal"
        raise HTTPException(status_code=502, detail=str(detail))
    return result


@app.post("/api/retell/turn")
def retell_turn(body: RetellTurnRequest) -> dict[str, Any]:
    """Retell custom-LLM / agent-response hook — Persona governance before TTS."""
    transcript = (body.transcript or body.user_message or "").strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="transcript or user_message required")
    session_id = body.session_id or body.call_id or "retell-default"
    payload = {
        "session_id": session_id,
        "call_id": body.call_id,
        "transcript": transcript,
        "voice_pause_ms": body.voice_pause_ms,
    }
    try:
        return _retell().handle_dict(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.websocket("/api/live/ws")
async def live_ws(websocket: WebSocket) -> None:
    try:
        runtime, _, _ = _ensure_runtime()
    except HTTPException as exc:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": exc.detail})
        await websocket.close(code=1011)
        return
    await handle_live_websocket(websocket, runtime)


def main() -> None:
    import logging
    import threading

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from pathlib import Path

    host = os.environ.get("PERSONA_CHAT_HOST", "127.0.0.1")
    port = int(os.environ.get("PERSONA_CHAT_PORT", "8765"))
    https_port = int(os.environ.get("PERSONA_CHAT_HTTPS_PORT", "8766"))
    ssl_cert = os.environ.get("PERSONA_SSL_CERT", "")
    ssl_key = os.environ.get("PERSONA_SSL_KEY", "")
    disable_ssl = os.environ.get("PERSONA_DISABLE_SSL", "").lower() in ("1", "true", "yes")
    if disable_ssl:
        ssl_cert = ""
        ssl_key = ""
    elif not ssl_cert or not ssl_key:
        module_root = Path(__file__).resolve().parents[3]
        default_cert = module_root / ".persona_ai" / "certs" / "dev-cert.pem"
        default_key = module_root / ".persona_ai" / "certs" / "dev-key.pem"
        if default_cert.is_file() and default_key.is_file():
            ssl_cert = str(default_cert)
            ssl_key = str(default_key)

    uvicorn_kwargs = {
        "ws_ping_interval": 30.0,
        "ws_ping_timeout": 120.0,
    }
    has_ssl = bool(
        ssl_cert
        and ssl_key
        and Path(ssl_cert).is_file()
        and Path(ssl_key).is_file()
    )

    if has_ssl and not disable_ssl:
        def _run_https() -> None:
            uvicorn.run(
                app,
                host=host,
                port=https_port,
                ssl_certfile=ssl_cert,
                ssl_keyfile=ssl_key,
                **uvicorn_kwargs,
            )

        threading.Thread(target=_run_https, daemon=True, name="persona-https").start()
        _log.info("PC web (HTTP):  http://127.0.0.1:%s", port)
        _log.info("Phone app (HTTPS): https://<LAN-IP>:%s", https_port)
        uvicorn.run(app, host=host, port=port, **uvicorn_kwargs)
        return

    if has_ssl:
        _log.info("TLS enabled — open https://127.0.0.1:%s", port)
        uvicorn.run(
            app,
            host=host,
            port=port,
            ssl_certfile=ssl_cert,
            ssl_keyfile=ssl_key,
            **uvicorn_kwargs,
        )
        return

    _log.info("HTTP mode — open http://127.0.0.1:%s in your PC browser", port)
    uvicorn.run(app, host=host, port=port, **uvicorn_kwargs)


if __name__ == "__main__":
    main()
