"""WebSocket bridge: browser PCM ↔ PersonaRuntime (brain) ↔ Gemini Live (mouth).

Persona decides first. Gemini Live only generates after BDV + VoiceDirective land
in the same user activity as the mic audio — one S2S reply, no GPT, no second
steer-turn fighting the first. Automatic Gemini VAD is off so the model cannot
speak before the engine. Avoid send_client_content here — interleaving with mic
realtime_input breaks transcription (per Gemini Live API).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from collections.abc import Callable

from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from persona_ai.llm.gemini_models import gemini_live_model
from persona_ai.runtime import PersonaRuntime
from persona_ai.core.types import Message
from persona_ai.session.models import SessionState
from persona_ai.web.persona_live import (
    LiveSteerMode,
    decide_live_action,
    governance_payload,
    load_session_messages,
    load_session_context,
    load_session_post_call,
    live_response_policy,
    plan_live_governance,
    session_overrides,
)
from persona_ai.web.live_web_search import (
    fetch_live_web_context,
    format_web_context_for_steer,
    needs_live_web_search,
)
from persona_ai.web.live_mode import LiveModeConfig
from persona_ai.web.call_config import LiveCallConfig
from persona_ai.web.dynamic_variables import merge_dynamic_variables, substitute_dynamic_variables
from persona_ai.web.post_call_config import PostCallConfig
from persona_ai.web.post_call_extraction import extract_post_call_data
from persona_ai.web.security_config import LiveSecurityConfig
from persona_ai.web.voice_config import LiveVoiceConfig
from persona_ai.web.webhook_config import LiveWebhookConfig
from persona_ai.web.webhook_delivery import build_call_object, deliver_webhook_event
from persona_ai.personality.papua_dialect_phrases import is_papua_dialect
from persona_ai.personality.papua_stt_lexicon import enrich_voice_config_for_papua, normalize_papua_transcript
from persona_ai.personality.papua_smart_barge_in import (
    clear_user_speech_start,
    mark_user_speech_start,
    should_allow_barge_in,
    speech_duration_s,
)
from persona_ai.personality.papua_laugh_track import mark_humor_turn, should_play_laugh_track, should_play_jedag_jedug
from persona_ai.web.conversation_controller import ConversationController
from persona_ai.personality.papua_loop_guard import (
    history_poisoned_by_santai,
    mark_block_santai_reply,
)
from persona_ai.web.conversation_flow_controller import (
    ConversationFlowController,
    analyze_user_turn,
)
from persona_ai.web.voice_instruction import (
    build_engine_directive_for_transcript,
    build_live_voice_instruction,
    pending_user_utterance,
)

_last_transcript: dict[str, str] = {}
PARTIAL_MIN_CHARS = 8
PARTIAL_DEBOUNCE_S = 0.12
GATE_HOLD_AFTER_AUDIO_S = 0.7
GREETING_MIC_FALLBACK_S = 8.0
# Idle Gemini WS drops with "keepalive ping timeout" if neither side sends for ~20s.
GEMINI_KEEPALIVE_IDLE_S = 12.0
GEMINI_KEEPALIVE_PCM = b"\x00" * 3200  # 100 ms silence @ 16 kHz mono s16le
# Gemini Live WS lifetime is ~10 minutes; refresh before GoAway/1008 abort.
GEMINI_LIVE_REFRESH_S = 420.0
# Natural S2S must not lock the mic pipeline — only governed/steered turns do.
NATURAL_TURN_STUCK_S = 12.0
# Natural S2S: gap between activity_end and next activity_start.
NATURAL_GAP_AFTER_END_S = 0.05
# Natural S2S silence endpoint — faster than governed VAD; no partial_stable spam.
NATURAL_SILENCE_COMMIT_S = 0.38
# Shorter tail after agent audio in natural mode — unlock user turn faster.
NATURAL_AGENT_REPLY_TAIL_S = 0.45

GEMINI_RESUME_COOLDOWN_S = 8.0
GEMINI_SESSION_EXPIRED_MSG = "Sesi voice Gemini habis. Sambungkan ulang panggilan."
MIC_CHUNK_DURATION_S = 0.1  # 1600 samples @ 16 kHz
MAX_AUDIO_QUEUE_CHUNKS = 8  # drop backlog beyond ~0.8 s
LOUD_MIC_RMS = 0.05
# Speaker echo after agent playback — ignore until the tail dies.
ECHO_HOLD_AFTER_AGENT_S = 2.0
ECHO_HOLD_AFTER_AGENT_MOBILE_S = 4.5
ECHO_OPEN_RMS = 0.10
# Force-clear ASR recovery when Gemini stops returning transcripts.
ASR_STUCK_RECOVERY_S = 5.0
PIPELINE_RECOVERY_COOLDOWN_S = 12.0
# Ignore borderline noise when resetting the post-speech silence timer.
SILENCE_RESET_RMS = 0.046
# Gemini sometimes emits this phrase with no real speech — require stronger mic evidence.
PHANTOM_MIN_PEAK_RMS = 0.05
_PHANTOM_ASR_PHRASES = frozenset(
    {
        "saya tidak tahu",
        "saya nggak tahu",
        "nggak tahu",
        "gak tau",
        "ga tau",
        "tidak tahu",
        "and dengan",
    }
)
# Extra wait only when there is no ASR yet — stable partials skip this grace.
STT_GRACE_AFTER_SILENCE_S = 0.25
# People pause mid-sentence — balance between responsiveness and mid-clause cuts.
PERSONA_COMMIT_MIN_SILENCE_S = 1.0
# Partials must be unchanged for this long before being considered stable.
PARTIAL_STABILITY_S = 0.38
FINAL_TRANSCRIPT_TIMEOUT_S = 0.55
MAX_ACTIVITY_WITHOUT_TRANSCRIPT_S = 3.0
# Gemini input transcription often arrives only after activity_end — end activity first, then wait.
MAX_ASR_WAIT_AFTER_END_S = 12.0
# Avoid rapid activity_start/end flapping that triggers Gemini WS 1007.
MIN_ACTIVITY_BEFORE_FLUSH_S = 1.80
# "Bro." / "Halo" is often a breath before the real sentence.
SHORT_UTTERANCE_SILENCE_S = 1.35
MIN_GAP_AFTER_ACTIVITY_END_S = 0.55
MAX_RECOVERY_MIC_CHUNKS = 20  # ~2 s — keep recent speech only
RECOVERY_QUEUE_HEADROOM = 3  # leave queue slots for live mic while dripping buffer
MAX_UNGOVERNED_BUFFER_BYTES = 144_000  # ~3 s @ 24 kHz mono s16le
MIN_PLAYABLE_PCM_BYTES = 160  # skip leftover 2-byte frames after an interrupted turn
# Last tokens that mean the ASR line is still mid-clause — wait for the rest.
_HANGING_ASR_LAST_TOKENS = frozenset(
    {
        "sama",
        "yang",
        "di",
        "ke",
        "dari",
        "dan",
        "atau",
        "tapi",
        "terus",
        "jadi",
        "kalau",
        "kalo",
        "untuk",
        "dengan",
        "soal",
        "tentang",
        "karena",
        "buat",
        "biar",
        "supaya",
        "with",
        "and",
        "or",
        "but",
        "to",
        "for",
        "of",
        "the",
        "kamu",
        "aku",
        "saya",
        "dia",
        "mereka",
        "kita",
        "ini",
        "itu",
        "mau",
        "akan",
        "bisa",
        "harus",
        "udah",
        "sudah",
        "belum",
        "lagi",
        "dong",
        "sih",
        "lah",
        "nih",
        "deh",
    }
)
HANGING_ASR_WAIT_S = 2.0
HANGING_ENDPOINT_SILENCE_S = 1.80
_WH_STARTERS = frozenset(
    {
        "kenapa",
        "mengapa",
        "gimana",
        "bagaimana",
        "apa",
        "siapa",
        "kapan",
        "dimana",
        "di mana",
        "kok",
        "knp",
        "why",
        "what",
        "how",
        "when",
        "where",
        "who",
    }
)
MAX_BDV_PAUSE_S = 0.8
_FILLER_TOKENS = frozenset(
    {
        "m",
        "mm",
        "mmm",
        "mmmm",
        "hmm",
        "hm",
        "hmmm",
        "uh",
        "um",
        "uhuh",
        "eh",
        "oh",
        "aa",
        "ahh",
    }
)
_log = logging.getLogger(__name__)
_DEBUG_LOG = Path(__file__).resolve().parents[3] / "debug-430d97.log"


def _debug_log(
    location: str,
    message: str,
    data: dict | None = None,
    *,
    hypothesis_id: str = "",
) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "430d97",
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
            "hypothesisId": hypothesis_id,
        }
        _DEBUG_LOG.open("a", encoding="utf-8").write(json.dumps(payload) + "\n")
    except Exception:
        pass
    # #endregion


def _is_voice_filler(text: str) -> bool:
    """True for hummed/backchannel noise that is not a new topic."""
    token = "".join(ch for ch in text.lower() if ch.isalnum())
    return token in _FILLER_TOKENS


def _should_govern_transcript(text: str) -> bool:
    """Skip hummed fillers and phantom ASR; keep short real words like 'Bro.' / 'Ya.'."""
    normalized = text.strip()
    if not normalized or _is_voice_filler(normalized):
        return False
    if _is_phantom_asr_phrase(normalized):
        return False
    token = "".join(ch for ch in normalized.lower() if ch.isalnum())
    return len(token) >= 2


def _asr_looks_unfinished(text: str) -> bool:
    """True when the latest ASR line still ends mid-clause (e.g. 'Kenapa kamu')."""
    raw = " ".join(text.strip().split())
    if not raw:
        return False
    if raw.endswith(("?", "!", ".")):
        return False
    if raw.endswith("...") or raw.endswith("…"):
        return True
    words = raw.rstrip(",").split()
    if not words:
        return False
    last = words[-1].lower()
    if last in _HANGING_ASR_LAST_TOKENS:
        return True
    first = words[0].lower()
    if first in _WH_STARTERS and len(words) <= 4:
        return True
    return False


def _asr_looks_brief(text: str) -> bool:
    """One- or two-word lines are often a breath, not the end of the turn."""
    raw = " ".join(text.strip().split())
    if not raw:
        return False
    words = raw.rstrip(".!?,;:").split()
    return 0 < len(words) <= 2


def _normalize_asr_phrase(text: str | None) -> str:
    raw = text or ""
    return " ".join("".join(c for c in raw.lower() if c.isalnum() or c.isspace()).split())


def _is_phantom_asr_phrase(text: str) -> bool:
    """Standalone confusion lines Gemini often hallucinates without user speech."""
    return _normalize_asr_phrase(text) in _PHANTOM_ASR_PHRASES


def _should_drop_phantom_asr(gov: dict, text: str) -> bool:
    if not _is_phantom_asr_phrase(text):
        return False
    peak = float(gov.get("turn_peak_mic_rms") or 0.0)
    phantom_min = _mic_threshold(gov, "phantom_min_peak_rms", PHANTOM_MIN_PEAK_RMS)
    if gov.get("had_loud_speech") and peak >= phantom_min:
        return False
    _log.info(
        "phantom ASR dropped: %r (peak_rms=%.4f had_loud=%s)",
        text,
        peak,
        gov.get("had_loud_speech"),
    )
    return True


def _echo_hold_seconds(gov: dict) -> float:
    if gov.get("embedded_app"):
        return ECHO_HOLD_AFTER_AGENT_MOBILE_S
    return ECHO_HOLD_AFTER_AGENT_S


_ASSISTANT_ECHO_CORPUS_MAX = 6000


def _append_assistant_echo_corpus(gov: dict, spoken: str) -> None:
    """Keep rolling agent speech for echo matching — segment finished must not wipe it."""
    chunk = " ".join(spoken.strip().split())
    if not chunk:
        return
    prev = (gov.get("assistant_echo_corpus") or "").strip()
    merged = f"{prev} {chunk}".strip() if prev else chunk
    if len(merged) > _ASSISTANT_ECHO_CORPUS_MAX:
        merged = merged[-_ASSISTANT_ECHO_CORPUS_MAX :]
    gov["assistant_echo_corpus"] = merged


def _assistant_echo_reference(gov: dict) -> str:
    corpus = (gov.get("assistant_echo_corpus") or "").strip()
    if corpus:
        return corpus
    live = (gov.get("assistant_text") or "").strip()
    if live:
        return live
    return (gov.get("last_assistant_spoken") or "").strip()


def _clear_assistant_echo_corpus(gov: dict) -> None:
    gov["assistant_echo_corpus"] = ""


def _word_overlap_ratio(a: str, b: str) -> float:
    wa = {w for w in a.lower().split() if len(w) > 2}
    wb = {w for w in b.lower().split() if len(w) > 2}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def _agent_reply_tail_hold_s(gov: dict) -> float:
    """How long after agent audio we treat the reply as still in-flight."""
    if _is_natural_s2s(gov):
        return max(NATURAL_AGENT_REPLY_TAIL_S, _echo_hold_seconds(gov) * 0.25)
    return _echo_hold_seconds(gov) + 1.0


def _agent_reply_already_started(gov: dict, *, now: float | None = None) -> bool:
    """True when Gemini audio for this turn is already playing — avoid steer that re-speaks."""
    clock = now if now is not None else time.monotonic()
    if gov.get("model_generating"):
        return True
    if gov.get("steered_audio_seen") or gov.get("awaiting_turn_complete"):
        return True
    last_fwd = gov.get("last_forward_at")
    hold = _agent_reply_tail_hold_s(gov)
    if isinstance(last_fwd, (int, float)) and last_fwd > 0:
        if clock - last_fwd < hold:
            return True
    return False


def _agent_playback_guard(gov: dict, *, now: float | None = None) -> bool:
    """True while agent audio is in flight — block echo from opening a user turn."""
    if gov.get("floor") == "agent":
        return True
    return _agent_reply_already_started(gov, now=now)


def _should_drop_echo_asr(gov: dict, text: str, *, now: float | None = None) -> bool:
    """Drop mic bleed of the agent's recent speech."""
    normalized = " ".join(text.strip().split())
    min_len = 8 if gov.get("embedded_app") else 12
    if len(normalized) < min_len:
        return False
    # Open user activity with real mic energy — trust ASR for this turn.
    if gov.get("gemini_activity_open") and gov.get("had_loud_speech"):
        peak = float(gov.get("turn_peak_mic_rms") or 0.0)
        if peak >= _mic_threshold(gov, "phantom_min_peak_rms", PHANTOM_MIN_PEAK_RMS):
            return False
    clock = now if now is not None else time.monotonic()
    hold = _echo_hold_seconds(gov)
    agent_active = _agent_reply_already_started(gov)
    recent_agent = agent_active
    last_fwd = gov.get("last_forward_at")
    if isinstance(last_fwd, (int, float)) and last_fwd > 0:
        if clock - last_fwd <= hold + 1.5:
            recent_agent = True
    last_tc = gov.get("last_turn_complete_at")
    if isinstance(last_tc, (int, float)) and last_tc > 0:
        if clock - last_tc <= hold + 2.5:
            recent_agent = True
    if gov.get("model_generating") or gov.get("floor") == "agent":
        recent_agent = True
    if not recent_agent:
        return False
    recovering = bool(
        gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery")
    )
    if (
        agent_active
        and gov.get("floor") == "agent"
        and not recovering
        and len(normalized) >= min_len
    ):
        _log.info("echo ASR dropped (agent in flight): %r", normalized[:80])
        return True
    assistant = _assistant_echo_reference(gov)
    if not assistant:
        if len(normalized) >= 40:
            _log.info("echo ASR dropped (long during agent tail): %r", normalized[:80])
            return True
        return False
    if len(normalized) >= 60:
        _log.info("echo ASR dropped (long during agent tail): %r", normalized[:80])
        return True
    spoken = " ".join(assistant.split()).lower()
    heard = normalized.lower()
    if heard in spoken or spoken in heard:
        _log.info("echo ASR dropped: %r", normalized[:80])
        return True
    if len(heard) >= 16 and len(spoken) >= 16 and heard[:32] == spoken[-32:]:
        _log.info("echo ASR dropped (suffix): %r", normalized[:80])
        return True
    if len(heard) >= 20 and heard[:40] == spoken[:40]:
        _log.info("echo ASR dropped (prefix): %r", normalized[:80])
        return True
    overlap_hi = 0.45 if gov.get("embedded_app") else 0.55
    overlap_lo = 0.22 if gov.get("embedded_app") else 0.30
    if _word_overlap_ratio(heard, spoken) >= overlap_hi:
        _log.info("echo ASR dropped (overlap): %r", normalized[:80])
        return True
    if len(heard) >= 24 and _word_overlap_ratio(heard, spoken) >= overlap_lo:
        _log.info("echo ASR dropped (partial overlap): %r", normalized[:80])
        return True
    return False


def _should_drop_spurious_asr(gov: dict, text: str) -> bool:
    return _should_drop_phantom_asr(gov, text) or _should_drop_echo_asr(gov, text)


def _recover_natural_turn_stuck(gov: dict, *, now: float | None = None) -> bool:
    """Clear natural-mode pipeline deadlock when turn_complete never arrives."""
    if not gov.get("natural_mode"):
        return False
    clock = now if now is not None else time.monotonic()
    last_tc = float(gov.get("last_turn_complete_at") or gov.get("session_started_at") or 0.0)
    last_end = float(gov.get("last_activity_end_at") or 0.0)
    anchor = max(last_tc, last_end)
    if anchor <= 0 or (clock - anchor) < NATURAL_TURN_STUCK_S:
        return False
    if not (
        gov.get("awaiting_turn_complete")
        or gov.get("model_generating")
        or not gov.get("ready_for_next_utterance", True)
    ):
        return False
    _log.warning(
        "natural turn stuck %.1fs — force reopen mic (awaiting_tc=%s model_gen=%s ready=%s)",
        clock - anchor,
        gov.get("awaiting_turn_complete"),
        gov.get("model_generating"),
        gov.get("ready_for_next_utterance"),
    )
    gov["awaiting_turn_complete"] = False
    gov["model_generating"] = False
    gov["accept_mic"] = True
    gov["ready_for_next_utterance"] = True
    gov["commit_scheduled"] = False
    gov["pending"] = False
    gov["mic_pacing_reset"] = True
    return True


def _voice_pipeline_stuck(gov: dict, *, now: float | None = None) -> str | None:
    """Return a recovery reason when mic is live but ASR/governance stalled."""
    if gov.get("gemini_resuming"):
        return None
    clock = now if now is not None else time.monotonic()
    if _answer_in_flight(gov) and not (
        gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery")
    ):
        return None

    asr_at = gov.get("activity_end_for_asr_at") or 0.0
    if (
        (gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery"))
        and isinstance(asr_at, (int, float))
        and asr_at > 0
    ):
        last_tx = float(gov.get("last_transcript_at") or 0.0)
        if clock - asr_at >= ASR_STUCK_RECOVERY_S and last_tx < asr_at:
            return "asr_recovery_timeout"

    last_any = float(gov.get("last_any_loud_mic_at") or 0.0)
    if last_any <= 0 or clock - last_any < ASR_STUCK_RECOVERY_S:
        return None
    last_tx = float(gov.get("last_transcript_at") or 0.0)
    if last_tx >= last_any - 0.5:
        return None

    if gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery"):
        return "speech_during_recovery"
    if _agent_playback_guard(gov, now=clock):
        return None
    if (
        gov.get("accept_mic")
        and gov.get("ready_for_next_utterance", True)
        and not gov.get("user_activity_open")
        and not gov.get("gemini_activity_open")
        and not _answer_in_flight(gov)
    ):
        return "speech_without_activity"
    return None


def _activity_handling(voice: LiveVoiceConfig) -> types.ActivityHandling:
    """New user activity may cut the agent reply. Sensitivity 0 keeps Gemini talking."""
    if voice.interruption_sensitivity <= 0:
        return types.ActivityHandling.NO_INTERRUPTION
    return types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS


def _live_connect_config(
    instruction: str,
    voice: LiveVoiceConfig,
    *,
    resumption_handle: str | None = None,
) -> types.LiveConnectConfig:
    """Persona owns turn-taking. Gemini must not auto-complete the user turn."""
    input_asr = voice.input_transcription_config()
    handle = (resumption_handle or "").strip() or None
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        generation_config=types.GenerationConfig(
            temperature=voice.generation_temperature,
        ),
        input_audio_transcription=input_asr,
        output_audio_transcription=types.AudioTranscriptionConfig(),
        speech_config=types.SpeechConfig(
            language_code=voice.language_code,
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice.voice_name,
                )
            ),
        ),
        system_instruction=types.Content(parts=[types.Part(text=instruction)]),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=True,
            ),
            activity_handling=_activity_handling(voice),
            turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
        ),
        # Always set this so Gemini sends session_resumption_update handles.
        # Do not set transparent=True — Gemini Developer API rejects it.
        session_resumption=types.SessionResumptionConfig(handle=handle),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow(),
        ),
    )


_GEMINI_RECONNECT_CLOSE_CODES = frozenset(
    {"1000", "1001", "1005", "1006", "1007", "1008", "1011", "1012", "1013"}
)


def _gemini_ws_close_code(exc: BaseException | str) -> str | None:
    token = str(exc).strip().split(None, 1)[0].rstrip(".,;:") if str(exc).strip() else ""
    if token.isdigit() and len(token) == 4:
        return token
    return None


def _is_gemini_goaway_error(exc: BaseException | str) -> bool:
    """True when Gemini Live WS closed and the browser call should keep going."""
    text = str(exc).lower()
    compact = text.replace(" ", "").replace("_", "")
    if _gemini_ws_close_code(exc) in _GEMINI_RECONNECT_CLOSE_CODES:
        return True
    if "goaway" in compact or "go away" in text:
        return True
    if "session durat" in text or "duration limit" in text:
        return True
    if "connection closed" in text or "connectionaborted" in compact:
        return True
    return False


def _browser_gemini_error(exc: BaseException | str) -> str:
    if _is_gemini_goaway_error(exc):
        return GEMINI_SESSION_EXPIRED_MSG
    return str(exc)


def _store_resumption_handle(gov: dict, update: object) -> None:
    handle = getattr(update, "new_handle", None)
    resumable = getattr(update, "resumable", None)
    if resumable is False:
        return
    if isinstance(handle, str) and handle.strip():
        gov["resumption_handle"] = handle.strip()


class _SwappableLiveSession:
    """Reconnect Gemini Live without rewriting every send/receive call site."""

    def __init__(self, session: object) -> None:
        object.__setattr__(self, "_session", session)

    def bind(self, session: object) -> None:
        object.__setattr__(self, "_session", session)

    def __getattr__(self, name: str):
        return getattr(object.__getattribute__(self, "_session"), name)


@asynccontextmanager
async def _connect_live_with_fallback(
    client: genai.Client,
    model: str,
    instruction: str,
    voice_cfg: LiveVoiceConfig,
    security_cfg: LiveSecurityConfig,
    *,
    resumption_handle: str | None = None,
):
    """Try primary voice, then Retell automatic fallback voice on connect failure."""
    candidates = [voice_cfg]
    fallback = security_cfg.effective_fallback_voice(voice_cfg.voice_name)
    if fallback:
        candidates.append(replace(voice_cfg, voice_name=fallback))
    last_exc: Exception | None = None
    for candidate in candidates:
        config = _live_connect_config(
            instruction, candidate, resumption_handle=resumption_handle
        )
        connect_cm = client.aio.live.connect(model=model, config=config)
        try:
            session = await connect_cm.__aenter__()
        except Exception as exc:
            last_exc = exc
            _log.warning("Gemini Live connect failed voice=%s: %s", candidate.voice_name, exc)
            continue
        if candidate.voice_name != voice_cfg.voice_name:
            _log.warning(
                "live connect using fallback voice=%s (primary=%s failed)",
                candidate.voice_name,
                voice_cfg.voice_name,
            )
        live_cm = {"cm": connect_cm}
        try:
            yield session, candidate, live_cm
        finally:
            cm = live_cm.pop("cm", None)
            if cm is not None:
                await cm.__aexit__(None, None, None)
        return
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Gemini Live connect failed")


def _should_open_user_activity(
    gov: dict, rms: float, *, loud_threshold: float | None = None, now: float | None = None
) -> bool:
    threshold = loud_threshold if loud_threshold is not None else _loud_mic_rms(gov)
    if gov.get("ignore_model_audio"):
        if gov.get("user_activity_open") or gov.get("gemini_activity_open"):
            return False
        if gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery"):
            return False
        if not gov.get("accept_mic"):
            return False
        return rms >= threshold
    if gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery"):
        return False
    if _late_asr_task_pending(gov):
        return False
    if gov.get("greeting_phase") or gov.get("user_activity_open") or gov.get("gemini_activity_open"):
        return False
    if not gov.get("accept_mic") and not _is_natural_s2s(gov):
        return False
    if not _is_natural_s2s(gov):
        if gov.get("awaiting_turn_complete"):
            return False
        if gov.get("model_generating"):
            return False
    if not _is_natural_s2s(gov) and not gov.get("ready_for_next_utterance", True):
        return False
    if not _is_natural_s2s(gov):
        if _answer_in_flight(gov) or gov.get("commit_scheduled"):
            return False
    clock = now if now is not None else time.monotonic()
    last_fwd = gov.get("last_forward_at")
    if _is_natural_s2s(gov) and _agent_playback_guard(gov, now=clock):
        # After barge-in floor=user, or loud speech — allow interrupt during agent tail.
        if gov.get("floor") != "user" and rms < threshold * 1.2:
            return False
    if (
        isinstance(last_fwd, (int, float))
        and last_fwd > 0
        and (clock - last_fwd) < _echo_hold_seconds(gov)
        and not (_is_natural_s2s(gov) and gov.get("floor") == "user")
    ):
        threshold = max(threshold, ECHO_OPEN_RMS)
    return rms >= threshold


def _mic_threshold(gov: dict, key: str, default: float) -> float:
    thresholds = gov.get("live_voice_thresholds")
    if isinstance(thresholds, dict) and key in thresholds:
        return float(thresholds[key])
    return default


def _partial_min_chars(gov: dict) -> int:
    return int(_mic_threshold(gov, "partial_min_chars", float(PARTIAL_MIN_CHARS)))


def _final_transcript_timeout_s(gov: dict) -> float:
    return _mic_threshold(gov, "final_transcript_timeout_s", FINAL_TRANSCRIPT_TIMEOUT_S)


def _max_asr_wait_after_end_s(gov: dict) -> float:
    return _mic_threshold(gov, "max_asr_wait_after_end_s", MAX_ASR_WAIT_AFTER_END_S)


def _loud_mic_rms(gov: dict) -> float:
    return _mic_threshold(gov, "loud_mic_rms", LOUD_MIC_RMS)


def _silence_reset_rms(gov: dict) -> float:
    return _mic_threshold(gov, "silence_reset_rms", SILENCE_RESET_RMS)


def _partial_stability_s(gov: dict) -> float:
    return _mic_threshold(gov, "partial_stability_s", PARTIAL_STABILITY_S)


def _stt_grace_after_silence_s(gov: dict) -> float:
    return _mic_threshold(gov, "stt_grace_after_silence_s", STT_GRACE_AFTER_SILENCE_S)


def _is_natural_s2s(gov: dict) -> bool:
    return bool(gov.get("natural_mode"))


def _should_buffer_mic(gov: dict) -> bool:
    """Hold mic locally until a new Gemini activity can open — never while one is live."""
    if _is_natural_s2s(gov):
        return False
    if gov.get("gemini_activity_open") or gov.get("user_activity_open"):
        return False
    if gov.get("awaiting_turn_complete"):
        return True
    if gov.get("model_generating"):
        return True
    if gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery"):
        return True
    if _late_asr_task_pending(gov):
        return True
    if gov.get("pending") or gov.get("commit_scheduled"):
        return True
    if _answer_in_flight(gov):
        return True
    return False


def _append_recovery_mic(gov: dict, pcm: bytes) -> None:
    buf: list[tuple[bytes, float]] = gov.setdefault("recovery_mic_buffer", [])
    rms = _pcm_rms(pcm)
    if len(buf) >= MAX_RECOVERY_MIC_CHUNKS:
        silent_idx = next(
            (i for i, (_, chunk_rms) in enumerate(buf) if chunk_rms < _loud_mic_rms(gov)),
            None,
        )
        if silent_idx is not None:
            buf.pop(silent_idx)
        else:
            buf.pop(0)
    buf.append((pcm, rms))


def _recovery_speech_pending(gov: dict) -> bool:
    if gov.get("recovery_mic_buffer"):
        return True
    return bool(gov.get("recovery_mic_pending"))


def _recovery_drip_pending(gov: dict) -> bool:
    return bool(gov.get("recovery_mic_pending"))


def _promote_recovery_for_flush(gov: dict) -> int:
    """Move relocated speech onto the drip queue so ASR flush can finish."""
    _schedule_recovery_mic_release(gov, "asr_flush")
    return len(gov.get("recovery_mic_pending") or [])


def _relocate_mic_queue_to_recovery(gov: dict, audio_queue: asyncio.Queue) -> int:
    """Move queued mic into recovery instead of dropping it before ASR flush."""
    moved = 0
    while True:
        try:
            pcm = audio_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if pcm is None:
            continue
        _append_recovery_mic(gov, pcm)
        moved += 1
    return moved


def _take_recovery_mic(gov: dict, *, min_rms: float | None = None) -> list[bytes]:
    raw = gov.pop("recovery_mic_buffer", [])
    chunks: list[bytes] = []
    for item in raw:
        if isinstance(item, tuple):
            pcm, rms = item
        else:
            pcm, rms = item, _pcm_rms(item)
        if min_rms is not None and rms < min_rms:
            continue
        chunks.append(pcm)
    return chunks


def _schedule_recovery_mic_release(gov: dict, reason: str) -> None:
    """Queue buffered mic for paced injection — never flood audio_queue at once."""
    buffered = _take_recovery_mic(gov, min_rms=_loud_mic_rms(gov))
    if not buffered:
        return
    pending: list[bytes] = gov.setdefault("recovery_mic_pending", [])
    pending.extend(buffered)
    while len(pending) > MAX_RECOVERY_MIC_CHUNKS:
        pending.pop(0)
    if not isinstance(gov.get("recovery_release_next_at"), (int, float)):
        gov["recovery_release_next_at"] = time.monotonic()
    _log.info(
        "queued %s mic chunks for paced release (%s, pending=%s)",
        len(buffered),
        reason,
        len(pending),
    )


def _drip_recovery_mic(gov: dict, audio_queue: asyncio.Queue) -> bool:
    pending: list[bytes] = gov.get("recovery_mic_pending") or []
    if not pending:
        return False
    if audio_queue.qsize() >= max(1, MAX_AUDIO_QUEUE_CHUNKS - RECOVERY_QUEUE_HEADROOM):
        return False
    now = time.monotonic()
    next_at = gov.get("recovery_release_next_at", 0.0)
    if not isinstance(next_at, (int, float)) or now < next_at:
        return False
    loud_floor = _loud_mic_rms(gov)
    while pending and _pcm_rms(pending[0]) < loud_floor:
        pending.pop(0)
    gov["recovery_mic_pending"] = pending
    if not pending:
        return False
    chunk = pending.pop(0)
    gov["recovery_mic_pending"] = pending
    gov["recovery_release_next_at"] = now + MIC_CHUNK_DURATION_S
    try:
        audio_queue.put_nowait(chunk)
        return True
    except asyncio.QueueFull:
        pending.insert(0, chunk)
        gov["recovery_mic_pending"] = pending
        return False


def _mark_awaiting_turn_complete(gov: dict) -> None:
    """Gemini must finish the steered turn before the next activity_start."""
    gov["awaiting_turn_complete"] = True
    gov["accept_mic"] = False


def _clear_steered_turn_state(gov: dict) -> None:
    gov["mode"] = LiveSteerMode.ALLOW
    gov["pending"] = False
    gov["steer_applied"] = True
    gov["awaiting_steered_turn"] = False
    gov["steered_audio_seen"] = False
    gov["play_steered"] = False
    gov["ungoverned_complete"] = False
    gov["fallback_final_scheduled"] = False
    gov["awaiting_turn_complete"] = False
    _clear_ungoverned_audio_buffer(gov)


def _commit_silence_s(voice: LiveVoiceConfig, gov: dict | None = None) -> float:
    if gov is not None:
        transcript = _latest_governance_transcript(gov)
        pause_ms = 0
        last_loud = gov.get("last_loud_mic_at")
        if isinstance(last_loud, (int, float)):
            pause_ms = int(max(0.0, time.monotonic() - last_loud) * 1000)
        ms = voice.effective_silence_duration_ms(
            transcript=transcript, voice_pause_ms=pause_ms
        )
        return max(PERSONA_COMMIT_MIN_SILENCE_S, ms / 1000.0)
    return max(PERSONA_COMMIT_MIN_SILENCE_S, voice.silence_duration_ms() / 1000.0)


def _update_partial_stability(gov: dict, text: str, *, now: float | None = None) -> None:
    """Track when partial ASR text last changed."""
    clock = now if now is not None else time.monotonic()
    normalized = text.strip()
    if normalized != gov.get("partial_stable_text"):
        gov["partial_stable_text"] = normalized
        gov["partial_stable_since"] = clock
    if normalized and not gov.get("first_partial_at"):
        gov["first_partial_at"] = clock


def _partial_is_stable(gov: dict, *, now: float | None = None) -> bool:
    clock = now if now is not None else time.monotonic()
    stable_text = gov.get("partial_stable_text") or ""
    stable_since = gov.get("partial_stable_since")
    if not stable_text.strip() or not isinstance(stable_since, (int, float)):
        return False
    return (clock - stable_since) >= _partial_stability_s(gov)


def _latency_mark(gov: dict, key: str, *, now: float | None = None) -> None:
    gov.setdefault("_latency_marks", {})[key] = (
        now if now is not None else time.monotonic()
    )


def _latency_delta_ms(gov: dict, start: str, end: str) -> int | None:
    marks = gov.get("_latency_marks") or {}
    if start not in marks or end not in marks:
        return None
    return max(0, int(round((marks[end] - marks[start]) * 1000)))


def _build_latency_metrics(
    gov: dict, *, turn_id: int, phase: str, extra: dict | None = None
) -> dict:
    """Structured E2E slices aligned with Retell orchestration budget."""
    metrics: dict = {
        "turn_id": turn_id,
        "phase": phase,
        "vad_wait_ms": _latency_delta_ms(gov, "speech_end", "user_commit"),
        "governance_ms": _latency_delta_ms(gov, "governance_start", "governance_done"),
        "steer_to_audio_ms": _latency_delta_ms(gov, "governance_done", "first_audio"),
        "commit_to_audio_ms": _latency_delta_ms(gov, "user_commit", "first_audio"),
        "connect_ms": _latency_delta_ms(gov, "connect_start", "session_active"),
        "greeting_to_audio_ms": _latency_delta_ms(gov, "session_active", "greeting_first_audio"),
    }
    out = {k: v for k, v in metrics.items() if v is not None}
    if extra:
        out.update(extra)
    return out


def _clear_turn_latency_marks(gov: dict) -> None:
    gov["_latency_marks"] = {}


def _next_turn_id(gov: dict) -> int:
    turn_id = int(gov.get("_latency_turn_id", 0)) + 1
    gov["_latency_turn_id"] = turn_id
    return turn_id


def _transcript_commit_reason(
    gov: dict, voice: LiveVoiceConfig, *, now: float | None = None
) -> str | None:
    """Why Persona may commit now: asr_final, partial_stable, incomplete_utterance, or None."""
    if gov.get("floor") == "agent" and _agent_reply_already_started(gov):
        return None
    if gov.get("model_generating") and gov.get("floor") != "user":
        return None
    if not gov.get("vad_turn_active"):
        return None
    if not gov.get("user_activity_open") or not gov.get("gemini_activity_open"):
        if not gov.get("activity_end_for_asr"):
            return None
    if gov.get("pending") or gov.get("commit_scheduled"):
        return None
    if not gov.get("user_activity_open") and _answer_in_flight(gov):
        return None
    if gov.get("flush_asr_after_send") or _recovery_drip_pending(gov):
        return None
    clock = now if now is not None else time.monotonic()
    last_loud = gov.get("last_loud_mic_at")
    started = gov.get("activity_started_at")
    if not isinstance(last_loud, (int, float)) or not isinstance(started, (int, float)):
        return None
    if not gov.get("had_loud_speech"):
        if clock - started < MAX_ACTIVITY_WITHOUT_TRANSCRIPT_S:
            return None
        if not gov.get("user_activity_open") and not gov.get("gemini_activity_open"):
            return None
        return "abandon_no_transcript"

    transcript = _latest_governance_transcript(gov)
    if transcript and _should_drop_spurious_asr(gov, transcript):
        return None
    if transcript and not _transcript_belongs_to_activity(gov):
        transcript = ""
    if gov.get("asr_finished") and transcript:
        return "asr_final"

    # Natural S2S: silence endpoint handled by natural_turn_committer — not governed VAD.
    if gov.get("natural_mode"):
        return None

    silence_s = _commit_silence_s(voice, gov)
    post_speech_s = clock - last_loud
    if post_speech_s < silence_s:
        return None

    recovering = bool(gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery"))
    hanging = bool(transcript) and _asr_looks_unfinished(transcript)
    brief = bool(transcript) and _asr_looks_brief(transcript) and not hanging
    if brief and post_speech_s < SHORT_UTTERANCE_SILENCE_S:
        return None
    # Guard: partial_stable should only fire for utterances that look syntactically
    # complete — ended with punctuation OR at least 5 words. Shorter mid-sentence
    # partials are often a natural pause before the user continues; forcing them
    # through the full silence gate prevents premature AI interruptions.
    raw_transcript = " ".join(transcript.strip().split()) if transcript else ""
    partial_looks_complete = (
        raw_transcript.endswith(("?", "!", ".", "…"))
        or len(raw_transcript.rstrip(".!?,;:").split()) >= 5
    )
    partial_ready = bool(
        transcript
        and _transcript_belongs_to_activity(gov)
        and _partial_is_stable(gov, now=clock)
        and not hanging
        and not recovering
        and partial_looks_complete
    )
    if partial_ready:
        return "partial_stable"

    if post_speech_s < silence_s + _stt_grace_after_silence_s(gov):
        return None

    if not transcript:
        if not gov.get("activity_end_for_asr"):
            if clock - started < MIN_ACTIVITY_BEFORE_FLUSH_S:
                return None
            if post_speech_s >= silence_s + _stt_grace_after_silence_s(gov):
                return "end_activity_for_asr"
            return None
        if not _asr_wait_elapsed(gov, now=clock):
            return None
        if _has_model_reply_since_flush(gov):
            return None
        return "abandon_no_transcript"

    first_partial = gov.get("first_partial_at")
    if not isinstance(first_partial, (int, float)) or first_partial <= 0:
        return None
    started = gov.get("activity_started_at")
    if isinstance(started, (int, float)) and first_partial < started:
        return None
    timeout_s = _final_transcript_timeout_s(gov)
    if hanging:
        timeout_s = max(timeout_s, HANGING_ASR_WAIT_S)
        if post_speech_s < HANGING_ENDPOINT_SILENCE_S:
            return None
    if clock - first_partial < timeout_s:
        return None

    return "incomplete_utterance"


def _natural_user_transcript(gov: dict) -> str:
    """Best-effort user words for natural S2S turn commit (final or stable partial)."""
    transcript = _latest_governance_transcript(gov)
    if transcript and transcript.strip():
        if _should_drop_spurious_asr(gov, transcript):
            return ""
        return transcript.strip()
    partial = (gov.get("partial_text") or "").strip()
    if partial and not _should_drop_spurious_asr(gov, partial):
        return partial
    return ""


def _natural_abandon_no_transcript_ready(
    gov: dict, *, now: float | None = None
) -> bool:
    """True when an open natural activity has no ASR after the abandon window."""
    if not gov.get("natural_mode"):
        return False
    if not gov.get("gemini_activity_open") or gov.get("natural_endpoint_sent"):
        return False
    clock = now if now is not None else time.monotonic()
    started = gov.get("activity_started_at")
    if not isinstance(started, (int, float)):
        return False
    if clock - started < MAX_ACTIVITY_WITHOUT_TRANSCRIPT_S:
        return False
    return not _natural_user_transcript(gov)


def _natural_silence_commit_ready(
    gov: dict, voice: LiveVoiceConfig, *, now: float | None = None
) -> bool:
    """True when natural mode should send activity_end after user silence."""
    if not gov.get("natural_mode"):
        return False
    if not gov.get("gemini_activity_open") or gov.get("natural_endpoint_sent"):
        return False
    if not gov.get("had_loud_speech"):
        return False
    if not _natural_user_transcript(gov):
        return False
    clock = now if now is not None else time.monotonic()
    if _agent_playback_guard(gov, now=clock) and gov.get("floor") != "user":
        return False
    peak = float(gov.get("turn_peak_mic_rms") or 0.0)
    if peak < _loud_mic_rms(gov):
        return False
    last_loud = gov.get("last_loud_mic_at")
    started = gov.get("activity_started_at")
    if not isinstance(last_loud, (int, float)) or not isinstance(started, (int, float)):
        return False
    if clock - started < 0.22:
        return False
    silence_s = max(
        NATURAL_SILENCE_COMMIT_S,
        voice.silence_duration_ms() / 1000.0,
    )
    return (clock - last_loud) >= silence_s


def _should_commit_user_activity(
    gov: dict, voice: LiveVoiceConfig, *, now: float | None = None
) -> bool:
    """True when local VAD + ASR stability say the user finished."""
    return _transcript_commit_reason(gov, voice, now=now) is not None


def _should_buffer_ungoverned_audio(gov: dict) -> bool:
    """Never hold a mute-gate buffer. While the user talks we drop; after that we play live."""
    del gov
    return False


def _is_playable_pcm(chunk: bytes) -> bool:
    return isinstance(chunk, (bytes, bytearray)) and len(chunk) >= MIN_PLAYABLE_PCM_BYTES


def _apply_natural_allow(gov: dict) -> list[bytes]:
    """Open the S2S playback gate after BDV RESPOND. Returns buffered PCM to flush."""
    chunks = [c for c in _flush_ungoverned_audio_buffer(gov) if _is_playable_pcm(c)]
    generation_done = bool(gov.pop("recovery_generation_complete", False))
    _clear_asr_recovery(gov)
    gov["mode"] = LiveSteerMode.ALLOW
    gov["pending"] = False
    gov["steer_applied"] = True
    gov["commit_scheduled"] = False
    gov["user_activity_open"] = False
    gov["held_audio"] = 0
    gov["stray_abort_sent"] = False
    if chunks:
        gov["last_forward_at"] = time.monotonic()
        gov["steered_audio_seen"] = True
    if generation_done:
        gov["play_steered"] = False
        gov["awaiting_steered_turn"] = False
        gov["awaiting_turn_complete"] = False
        gov["model_generating"] = False
        gov["accept_mic"] = True
        gov["ready_for_next_utterance"] = True
        gov["mic_pacing_reset"] = True
    else:
        gov["play_steered"] = True
        gov["awaiting_steered_turn"] = True
        gov["steered_audio_seen"] = bool(chunks)
        gov["model_generating"] = True
        gov["ready_for_next_utterance"] = False
        _mark_awaiting_turn_complete(gov)
    return chunks


def _should_abort_stray_model(gov: dict) -> bool:
    del gov
    return False


def _clear_ungoverned_audio_buffer(gov: dict) -> None:
    gov["ungoverned_audio_buffer"] = []
    gov["ungoverned_audio_buffer_bytes"] = 0


def _append_ungoverned_audio(gov: dict, chunk: bytes) -> bool:
    """Buffer model PCM until governance opens the gate. False = overflow drop."""
    total = gov.get("ungoverned_audio_buffer_bytes", 0) + len(chunk)
    if total > MAX_UNGOVERNED_BUFFER_BYTES:
        gov["ungoverned_audio_drops"] = gov.get("ungoverned_audio_drops", 0) + 1
        _clear_ungoverned_audio_buffer(gov)
        return False
    gov.setdefault("ungoverned_audio_buffer", []).append(chunk)
    gov["ungoverned_audio_buffer_bytes"] = total
    gov["held_audio"] = gov.get("held_audio", 0) + 1
    return True


def _flush_ungoverned_audio_buffer(gov: dict) -> list[bytes]:
    chunks = gov.pop("ungoverned_audio_buffer", [])
    gov["ungoverned_audio_buffer_bytes"] = 0
    return chunks


def _bdv_pause_seconds(output) -> float:
    voice = getattr(output, "voice", None)
    delay_ms = getattr(voice, "timing_delay_ms", 0) or 0
    return min(MAX_BDV_PAUSE_S, max(0.0, delay_ms / 1000.0))


def _note_mic_rms(gov: dict, rms: float, *, now: float | None = None) -> None:
    """Track user speech and end-of-speech timing with noise hysteresis."""
    clock = now if now is not None else time.monotonic()
    in_activity = gov.get("user_activity_open") or gov.get("gemini_activity_open")
    if in_activity:
        peak = float(gov.get("turn_peak_mic_rms") or 0.0)
        if rms > peak:
            gov["turn_peak_mic_rms"] = rms
    if in_activity and rms >= _loud_mic_rms(gov):
        gov["had_loud_speech"] = True
    if rms >= _silence_reset_rms(gov):
        gov["last_loud_mic_at"] = clock
    elif not gov.get("had_loud_speech") and rms >= _loud_mic_rms(gov):
        gov["last_loud_mic_at"] = clock
    if rms >= _loud_mic_rms(gov):
        if not (gov.get("embedded_app") and _agent_playback_guard(gov, now=clock)):
            gov["last_any_loud_mic_at"] = clock
        if gov.get("model_generating") or _answer_in_flight(gov):
            mark_user_speech_start(gov)


def _user_spoke_in_activity(gov: dict, voice: LiveVoiceConfig) -> bool:
    if gov.get("had_loud_speech"):
        return True
    last_loud = gov.get("last_loud_mic_at")
    started = gov.get("activity_started_at")
    if not isinstance(last_loud, (int, float)) or not isinstance(started, (int, float)):
        return False
    min_speech_s = max(0.08, voice.prefix_padding_ms() / 1000.0)
    return (last_loud - started) >= min_speech_s


def _transcript_belongs_to_activity(gov: dict) -> bool:
    """True when ASR partial/final timestamps belong to the current mic activity."""
    started = gov.get("activity_started_at")
    if not isinstance(started, (int, float)) or started < 0:
        return False
    first_partial = gov.get("first_partial_at")
    if isinstance(first_partial, (int, float)) and first_partial >= started:
        return True
    last_at = gov.get("last_transcript_at")
    return isinstance(last_at, (int, float)) and last_at >= started


def _should_accept_input_transcription(gov: dict) -> bool:
    """Only accept Gemini ASR while a user turn or post-flush recovery is active."""
    if gov.get("greeting_phase"):
        return True
    if gov.get("user_activity_open") or gov.get("gemini_activity_open"):
        return True
    return bool(gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery"))


def _asr_wait_elapsed(gov: dict, *, now: float) -> bool:
    ended_at = gov.get("activity_end_for_asr_at")
    if not gov.get("activity_end_for_asr"):
        return False
    if not isinstance(ended_at, (int, float)) or ended_at <= 0:
        return False
    return (now - ended_at) >= _max_asr_wait_after_end_s(gov)


def _pcm_rms(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    import struct

    count = len(pcm) // 2
    samples = struct.unpack(f"<{count}h", pcm[: count * 2])
    if not samples:
        return 0.0
    mean_sq = sum(s * s for s in samples) / len(samples)
    return (mean_sq**0.5) / 32768.0


def _idle_steer_mode(gov: dict) -> LiveSteerMode:
    """Audio stays open. Pause while the user talks is barge-in, not a mute gate."""
    del gov
    return LiveSteerMode.ALLOW


def _has_model_reply_since_flush(gov: dict) -> bool:
    """True when Gemini already spoke after activity_end — do not abandon into silence."""
    if gov.get("model_generating") or gov.get("recovery_generation_complete"):
        return True
    if gov.get("ungoverned_audio_buffer"):
        return True
    last_fwd = gov.get("last_forward_at")
    ended = gov.get("activity_end_for_asr_at")
    return (
        isinstance(last_fwd, (int, float))
        and isinstance(ended, (int, float))
        and ended > 0
        and last_fwd >= ended
    )


def _should_forward_governed_audio(gov: dict) -> bool:
    """Play Gemini audio except while the user holds the floor or a ghost turn flushed."""
    if gov.get("ignore_model_audio"):
        return False
    if gov.get("greeting_phase"):
        return True
    if gov.get("user_activity_open"):
        return False
    recovering = bool(gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery"))
    if recovering:
        has_asr = False
        for key in ("last_user_transcript", "partial_text"):
            value = gov.get(key)
            if isinstance(value, str) and value.strip():
                has_asr = True
                break
        if not has_asr and not gov.get("had_loud_speech"):
            return False
        peak = float(gov.get("turn_peak_mic_rms") or 0.0)
        if not has_asr and peak < _mic_threshold(gov, "phantom_min_peak_rms", PHANTOM_MIN_PEAK_RMS):
            return False
    return True


def _take_floor(gov: dict, speaker: str) -> bool:
    """True when the speaking floor actually changes (agent ↔ user)."""
    if speaker not in ("agent", "user"):
        return False
    if gov.get("floor") == speaker:
        return False
    gov["floor"] = speaker
    return True


def _floor_event(speaker: str, *, reason: str = "") -> dict:
    payload: dict = {"type": "floor", "speaker": speaker}
    if reason:
        payload["reason"] = reason
    return payload


def _latest_governance_transcript(gov: dict) -> str:
    """Prefer the longest growing ASR line so mid-sentence partials are not governed alone."""
    candidates: list[str] = []
    for key in ("last_user_transcript", "partial_text"):
        value = gov.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    if not candidates:
        return ""
    return max(candidates, key=len)


def _should_schedule_governance_fallback(gov: dict, *, now: float | None = None) -> bool:
    """Disabled: Persona commits on local VAD / ASR finished, never on held S2S audio."""
    del gov, now
    return False


def _should_close_audio_gate(gov: dict, *, now: float | None = None) -> bool:
    """Re-lock audio after the steered reply; keep open for leftover ungoverned turn_complete."""
    if gov.get("pending"):
        return False
    final_task = gov.get("final_task")
    if final_task is not None and not final_task.done():
        return False
    if gov.get("awaiting_steered_turn") and not gov.get("play_steered"):
        return False
    if gov.get("awaiting_steered_turn") and gov.get("play_steered") and not gov.get("steered_audio_seen"):
        return False
    if gov.get("steer_applied") and gov.get("play_steered"):
        last_fwd = gov.get("last_forward_at")
        if isinstance(last_fwd, (int, float)):
            clock = now if now is not None else time.monotonic()
            if clock - last_fwd < GATE_HOLD_AFTER_AUDIO_S:
                return False
    return True


def _answer_in_flight(gov: dict) -> bool:
    """True while Persona is steering or Gemini is still producing the governed reply."""
    if gov.get("pending") or gov.get("awaiting_steered_turn"):
        return True
    if gov.get("awaiting_turn_complete"):
        return True
    if gov.get("model_generating") and not (
        gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery")
    ):
        return True
    final_task = gov.get("final_task")
    return final_task is not None and not final_task.done()


def _live_session_idle(gov: dict) -> bool:
    return not (
        gov.get("user_activity_open")
        or gov.get("gemini_activity_open")
        or gov.get("model_generating")
        or _answer_in_flight(gov)
        or gov.get("pending")
    )


def _apply_barge_in(gov: dict, *, soft: bool = False) -> None:
    """User stole the floor — drop leftover agent audio and reopen the next utterance."""
    for key in ("partial_task", "final_task", "late_asr_task"):
        task = gov.get(key)
        if task is not None and not task.done():
            task.cancel()
        gov[key] = None
    gov["pending"] = False
    gov["mode"] = LiveSteerMode.ALLOW
    gov["steer_applied"] = True
    gov["awaiting_steered_turn"] = False
    gov["steered_audio_seen"] = False
    gov["play_steered"] = False
    gov["ungoverned_complete"] = False
    gov["fallback_final_scheduled"] = False
    gov["awaiting_turn_complete"] = False
    gov["accept_mic"] = True
    gov["ready_for_next_utterance"] = True
    gov["model_generating"] = False
    gov["recovery_generation_complete"] = False
    gov["awaiting_asr_recovery"] = False
    gov["ignore_model_audio"] = True
    gov["greeting_phase"] = False
    _clear_asr_recovery(gov)
    gov["partial_text"] = ""
    gov["partial_stable_text"] = ""
    gov["partial_stable_since"] = 0.0
    gov["first_partial_at"] = 0.0
    gov["queued_transcript"] = ""
    gov["final_scheduled_for"] = ""
    gov["last_forward_at"] = 0.0
    gov["user_activity_open"] = False
    gov["commit_scheduled"] = False
    gov["close_activity"] = not soft
    gov["asr_finished"] = False
    _clear_assistant_echo_corpus(gov)
    _clear_ungoverned_audio_buffer(gov)


def _drop_queued_audio(browser_out: asyncio.Queue) -> int:
    """Remove pending agent PCM so barge-in cuts speech immediately (Retell `clear`)."""
    kept: list = []
    dropped = 0
    while True:
        try:
            item = browser_out.get_nowait()
        except asyncio.QueueEmpty:
            break
        if isinstance(item, dict) and item.get("type") == "audio":
            dropped += 1
            continue
        kept.append(item)
    for item in kept:
        try:
            browser_out.put_nowait(item)
        except asyncio.QueueFull:
            break
    return dropped


def _should_schedule_late_asr(gov: dict) -> bool:
    """Only recover ASR after flush/abandon — not after a normal transcript commit."""
    return bool(gov.get("awaiting_asr_recovery") or gov.get("activity_end_for_asr"))


def _reset_vad_turn(gov: dict) -> None:
    """Close the local VAD turn so the committer cannot re-fire abandon in a loop."""
    _clear_asr_recovery(gov)
    gov["vad_turn_active"] = False
    gov["activity_started_at"] = 0.0
    gov["last_loud_mic_at"] = 0.0
    gov["had_loud_speech"] = False
    gov["asr_finished"] = False
    gov["partial_text"] = ""
    gov["partial_stable_text"] = ""
    gov["partial_stable_since"] = 0.0
    gov["first_partial_at"] = 0.0
    gov["last_user_transcript"] = ""
    gov["turn_peak_mic_rms"] = 0.0
    gov["natural_endpoint_sent"] = False


def _clear_asr_recovery(gov: dict) -> None:
    gov["awaiting_asr_recovery"] = False
    gov["activity_end_for_asr"] = False
    gov["activity_end_for_asr_at"] = 0.0
    gov["asr_recovery_partial"] = ""


def _late_asr_task_pending(gov: dict) -> bool:
    task = gov.get("late_asr_task")
    return task is not None and not task.done()


def _lock_asr_recovery_partial(gov: dict, text: str) -> str:
    """Keep the first ASR line during post-flush recovery — reject Gemini revisions."""
    if not (gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery")):
        return text
    locked = (gov.get("asr_recovery_partial") or "").strip()
    if not locked:
        gov["asr_recovery_partial"] = text
        return text
    if text == locked or locked in text or text in locked:
        if len(text) > len(locked):
            gov["asr_recovery_partial"] = text
        return gov["asr_recovery_partial"]
    _log.info("ignore ASR swap during recovery: %r (keeping %r)", text, locked)
    return locked


def _mark_asr_recovery(gov: dict, *, now: float | None = None) -> None:
    clock = now if now is not None else time.monotonic()
    gov["awaiting_asr_recovery"] = True
    gov["activity_end_for_asr"] = True
    gov["activity_end_for_asr_at"] = clock
    gov["asr_recovery_partial"] = ""
    gov["play_steered"] = False
    gov["mode"] = LiveSteerMode.ALLOW


def _should_start_final_governance(gov: dict, transcript: str, last_by_session: dict, session_id: str) -> bool:
    normalized = transcript.strip()
    if not normalized:
        return False
    if last_by_session.get(session_id) == normalized:
        return False
    if gov.get("final_scheduled_for") == normalized:
        return False
    if gov.get("awaiting_turn_complete"):
        return False
    if _answer_in_flight(gov):
        # Don't steal the floor mid-reply — echo/partials were chopping speech.
        return False
    if not gov.get("ready_for_next_utterance", True):
        return False
    return True


async def _steer_gemini_session(session, steer_prompt: str, *, send_lock: asyncio.Lock) -> None:
    """Inject Persona governance via realtime text (same channel as mic audio)."""
    async with send_lock:
        await session.send_realtime_input(text=steer_prompt)


async def _schedule_pre_turn_loop_nudge(
    gov: dict,
    session,
    *,
    send_lock: asyncio.Lock,
) -> None:
    """Fire loop nudge without blocking activity_end — latency first."""
    from persona_ai.personality.papua_loop_guard import (
        build_pre_turn_loop_nudge,
        consume_pre_turn_loop_nudges,
        pre_turn_loop_nudge_needed,
    )

    if not pre_turn_loop_nudge_needed(gov):
        return
    nudge = build_pre_turn_loop_nudge(gov)
    if not nudge:
        return
    consume_pre_turn_loop_nudges(gov)
    try:
        await _steer_gemini_session(session, nudge, send_lock=send_lock)
        _log.info("pre-turn loop nudge sent (async)")
    except Exception:
        _log.exception("pre-turn loop nudge failed")


def _natural_persist_user_turn(runtime: PersonaRuntime, session_id: str, text: str) -> None:
    """Lightweight session write for natural S2S — skip full Persona pipeline."""
    session = runtime._store.load(session_id)
    if session is None:
        session = SessionState.new(
            session_id,
            profile_warmth=runtime.personality_profile.warmth,
        )
    session.messages.append(Message(role="user", text=text))
    session.turn_index += 1
    runtime._store.save(session)


def _observe_model_turn_complete(gov: dict, text: str) -> None:
    """Sidecar hook 1 — observe full assistant transcript after turn completes."""
    if not gov.get("natural_mode"):
        return
    cleaned = text.strip()
    if cleaned:
        from persona_ai.personality.papua_loop_guard import note_assistant_turn

        note_assistant_turn(gov, cleaned)
    conv = gov.get("conv_ctrl")
    if not isinstance(conv, ConversationController):
        return
    cleaned = text.strip()
    if not cleaned:
        return
    flow = gov.get("flow_ctrl")
    if isinstance(flow, ConversationFlowController):
        flow.on_assistant_finished(cleaned)
    category = conv.on_model_turn_complete(cleaned)
    if category:
        _log.info(
            "conversation controller observe category=%s state=%s",
            category,
            conv.to_dict(),
        )


def _clear_assistant_transcript_buffer(gov: dict) -> None:
    gov["assistant_text"] = ""
    _clear_assistant_echo_corpus(gov)


def _finalize_assistant_turn(
    gov: dict,
    *,
    persist: Callable[[str], None] | None = None,
) -> str | None:
    """Observe assistant transcript exactly once, then clear buffer."""
    text = (gov.get("assistant_text") or "").strip()
    if not text:
        _clear_assistant_transcript_buffer(gov)
        return None
    if gov.get("assistant_turn_observed"):
        _clear_assistant_transcript_buffer(gov)
        return None
    gov["assistant_turn_observed"] = True
    if persist is not None:
        persist(text)
    _observe_model_turn_complete(gov, text)
    _clear_assistant_transcript_buffer(gov)
    return text


def _mark_conversation_steer_deferred(gov: dict) -> None:
    conv = gov.get("conv_ctrl")
    pending_conv = isinstance(conv, ConversationController) and conv.state.pending_steer
    if pending_conv:
        gov["conv_steer_deferred"] = True


async def _on_safe_turn_boundary(
    gov: dict,
    session,
    *,
    reason: str,
    send_lock: asyncio.Lock,
    yield_turn: Callable[[str], None],
    persist: Callable[[str], None] | None = None,
) -> None:
    """Unified safe boundary: finalize transcript → yield floor → defer steer (no 2nd speech)."""
    epoch = int(gov.get("agent_reply_epoch") or 0)
    if epoch > 0 and gov.get("boundary_handled_epoch") == epoch:
        _log.info("skip duplicate turn boundary epoch=%s reason=%s", epoch, reason)
        return
    if epoch > 0:
        gov["boundary_handled_epoch"] = epoch

    finalized = _finalize_assistant_turn(gov, persist=persist)
    if finalized:
        _log.info(
            "assistant turn finalized reason=%s chars=%s",
            reason,
            len(finalized),
        )
    yield_turn(reason)
    conv = gov.get("conv_ctrl")
    if (
        gov.get("natural_mode")
        and isinstance(conv, ConversationController)
        and conv.deliver_steer
    ):
        _mark_conversation_steer_deferred(gov)
        _log.info(
            "conversation steer deferred reason=%s pending=%s",
            reason,
            bool(gov.get("conv_steer_deferred")),
        )


async def _flush_pending_conversation_steer(
    gov: dict,
    session,
    *,
    send_lock: asyncio.Lock,
    reason: str = "",
) -> None:
    """Deliver queued steer only when pipeline is idle."""
    if not gov.get("natural_mode"):
        return
    if (
        gov.get("user_activity_open")
        or gov.get("model_generating")
        or gov.get("gemini_activity_open")
        or gov.get("awaiting_turn_complete")
    ):
        return
    flow = gov.get("flow_ctrl")
    if isinstance(flow, ConversationFlowController):
        flow.take_correction_steer()
    conv = gov.get("conv_ctrl")
    if not isinstance(conv, ConversationController):
        return
    steer = conv.take_pending_steer()
    if not steer:
        return
    try:
        await _steer_gemini_session(session, steer, send_lock=send_lock)
        conv.mark_steer_sent()
        _log.info(
            "conversation steer delivered reason=%s len=%s",
            reason or "unknown",
            len(steer),
        )
    except Exception:
        _log.exception("conversation steer delivery failed reason=%s", reason or "unknown")


async def _await_client_session(ws: WebSocket, *, timeout: float = 12.0) -> dict:
    """Wait for client session payload (voice + session_id) before Gemini connect."""
    try:
        while True:
            message = await asyncio.wait_for(ws.receive(), timeout=timeout)
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect()
            text = message.get("text")
            if not text:
                continue
            payload = json.loads(text)
            if payload.get("type") == "session":
                return payload
    except asyncio.TimeoutError:
        _log.warning("client session timeout — using preset voice defaults")
        return {}


async def handle_live_websocket(ws: WebSocket, runtime: PersonaRuntime) -> None:
    await ws.accept()
    api_key = runtime.llm_adapter.api_key if hasattr(runtime.llm_adapter, "api_key") else ""
    if not api_key:
        import os

        api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        await ws.send_json({"type": "error", "message": "GEMINI_API_KEY tidak diset"})
        await ws.close()
        return

    model = gemini_live_model()
    profile = runtime.personality_profile
    voice_cfg = LiveVoiceConfig.from_profile(profile)
    call_cfg = LiveCallConfig.from_profile(profile)
    post_call_cfg = PostCallConfig.from_profile(profile)
    security_cfg = LiveSecurityConfig.from_profile(profile)
    webhook_cfg = LiveWebhookConfig.from_profile(profile)
    live_mode = LiveModeConfig.from_profile(profile)

    await ws.send_json(
        {
            "type": "status",
            "state": "connecting",
            "voice_config": voice_cfg.to_client_dict(),
            "call_config": call_cfg.to_client_dict(),
            "post_call_config": post_call_cfg.to_client_dict(),
            "security_config": security_cfg.to_client_dict(),
            "webhook_config": webhook_cfg.to_client_dict(),
            "live_mode": live_mode.to_client_dict(),
        }
    )

    session_payload = await _await_client_session(ws)
    if session_payload.get("session_id"):
        session_id = str(session_payload["session_id"])
    else:
        session_id = f"live-{uuid.uuid4().hex[:10]}"
    voice_cfg = voice_cfg.with_client_overrides(
        voice_name=session_payload.get("voice_name"),
        language_code=session_payload.get("language_code"),
    )
    dyn_vars = merge_dynamic_variables(
        security_cfg.default_dynamic_variables,
        session_payload.get("dynamic_variables"),
        {"agent_name": profile.display_name},
    )
    if voice_cfg.begin_message:
        voice_cfg = replace(
            voice_cfg,
            begin_message=substitute_dynamic_variables(voice_cfg.begin_message, dyn_vars),
        )
    prior_messages, prior_post_call = load_session_context(runtime, session_id)
    has_history = bool(prior_messages) or bool(prior_post_call)
    _last_transcript.pop(session_id, None)
    live_dialect = session_payload.get("dialect") or session_payload.get("speaking_style")
    if isinstance(live_dialect, str):
        live_dialect = live_dialect.strip().lower() or None
    else:
        live_dialect = None
    if not live_dialect and (profile.default_language or "id") == "id":
        live_dialect = "papua"
    if is_papua_dialect(live_dialect):
        voice_cfg = enrich_voice_config_for_papua(voice_cfg)
    # No scripted opening steer — avoids double greeting with system instruction.
    opening_prompt = None
    instruction = build_live_voice_instruction(
        profile,
        history=prior_messages,
        dialect=live_dialect,
        post_call=prior_post_call,
    )
    prosody_sim = session_payload.get("papua_prosody_sim") or session_payload.get("prosody_sim")
    if prosody_sim and is_papua_dialect(live_dialect):
        from persona_ai.personality.papua_prosody_sim import prosody_sim_prompt_lines

        sim_lines = prosody_sim_prompt_lines(live_dialect, prosody_sim)
        if sim_lines:
            instruction = f"{instruction}\n\n" + "\n".join(sim_lines)
    _log.info(
        "live session voice=%s lang=%s dialect=%s session=%s history=%s resume=%s",
        voice_cfg.voice_name,
        voice_cfg.language_code,
        live_dialect or "-",
        session_id,
        len(prior_messages),
        has_history,
    )

    client = genai.Client(api_key=api_key)
    stop = asyncio.Event()
    client_ready = asyncio.Event()
    session_ref = {"id": session_id}

    gov: dict = {
        "mode": LiveSteerMode.ALLOW,
        "dialect": live_dialect,
        "papua_prosody_sim": prosody_sim if isinstance(prosody_sim, dict) else None,
        "pending": False,
        "steer_applied": False,
        "partial_text": "",
        "partial_task": None,
        "final_task": None,
        "late_asr_task": None,
        "lock": asyncio.Lock(),
        "mic_chunks": 0,
        "accept_mic": False,
        "greeting_phase": opening_prompt is not None,
        "resume_call": has_history,
        "assistant_text": "",
        "assistant_echo_corpus": "",
        "laugh_track_pending": False,
        "user_speech_started_at": 0.0,
        "last_assistant_spoken": "",
        "held_audio": 0,
        "last_gemini_send": time.monotonic(),
        "last_activity_end_at": 0.0,
        "last_user_transcript": "",
        "last_transcript_at": 0.0,
        "fallback_final_scheduled": False,
        "awaiting_steered_turn": False,
        "awaiting_turn_complete": False,
        "model_generating": False,
        "ignore_model_audio": False,
        "recovery_generation_complete": False,
        "steered_audio_seen": False,
        "play_steered": False,
        "ungoverned_complete": False,
        "ready_for_next_utterance": False,
        "queued_transcript": "",
        "final_scheduled_for": "",
        "last_forward_at": 0.0,
        "last_loud_mic_at": 0.0,
        "last_any_loud_mic_at": 0.0,
        "last_pipeline_recovery_at": 0.0,
        "had_loud_speech": False,
        "live_voice_thresholds": voice_cfg.live_thresholds(),
        "last_turn_complete_at": 0.0,
        "memory_refresh_at_count": 0,  # legacy — mid-call refresh disabled
        "last_governed_transcript": "",
        "user_activity_open": False,
        "gemini_activity_open": False,
        "activity_started_at": 0.0,
        "commit_scheduled": False,
        "close_activity": False,
        "flush_asr_after_send": False,
        "voice_pause_ms": 0,
        "asr_finished": False,
        "activity_end_for_asr": False,
        "activity_end_for_asr_at": 0.0,
        "awaiting_asr_recovery": False,
        "vad_turn_active": False,
        "partial_stable_text": "",
        "partial_stable_since": 0.0,
        "first_partial_at": 0.0,
        "ungoverned_audio_buffer": [],
        "ungoverned_audio_buffer_bytes": 0,
        "ungoverned_audio_drops": 0,
        "_latency_turn_id": 0,
        "session_started_at": time.monotonic(),
        "last_user_activity_at": time.monotonic(),
        "keypad_buffer": "",
        "keypad_task": None,
        "post_call_scheduled": False,
        "call_end_reason": "session_end",
        "webhook_call_ended_sent": False,
        "webhook_call_started_sent": False,
        "natural_mode": live_mode.is_natural,
        "natural_endpoint_sent": False,
        "recent_assistant_lines": [],
        "assistant_opener_streak": 0,
        "santai_phrase_streak": 0,
        "mau_offer_streak": 0,
        "block_santai_reply": False,
        "last_assistant_opener": "",
        "conv_ctrl": ConversationController.from_live_mode(live_mode),
        "flow_ctrl": ConversationFlowController(),
        "assistant_turn_observed": False,
        "agent_reply_epoch": 0,
        "boundary_handled_epoch": -1,
        "conv_steer_deferred": False,
        "embedded_app": bool(session_payload.get("embedded_app")),
        "floor": None,
        "resumption_handle": "",
        "gemini_connected_at": 0.0,
        "go_away_at": 0.0,
        "gemini_resuming": False,
        "resume_times": [],
    }
    if opening_prompt is None:
        gov["accept_mic"] = True
        gov["mic_pacing_reset"] = True
        gov["ready_for_next_utterance"] = True
        if live_mode.is_natural:
            gov["mode"] = LiveSteerMode.ALLOW
            gov["steer_applied"] = True

    try:
        _latency_mark(gov, "connect_start")
        async with _connect_live_with_fallback(
            client, model, instruction, voice_cfg, security_cfg
        ) as (raw_session, voice_cfg, live_cm):
            session = _SwappableLiveSession(raw_session)
            gov["gemini_connected_at"] = time.monotonic()
            session_send_lock = asyncio.Lock()
            resume_lock = asyncio.Lock()
            audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=64)
            # Never await browser WS inside session.receive() — that stalls Gemini
            # keepalive pings and drops user transcription mid-utterance.
            browser_out: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=128)

            async def resume_gemini(reason: str) -> bool:
                """Open a new Gemini Live connection; keep the browser call alive."""
                async with resume_lock:
                    connected = float(gov.get("gemini_connected_at") or 0)
                    if (
                        connected > 0
                        and (time.monotonic() - connected) < GEMINI_RESUME_COOLDOWN_S
                    ):
                        _log.info(
                            "gemini resume skipped (%s) — session just refreshed",
                            reason,
                        )
                        return True
                    now = time.monotonic()
                    recent = [
                        t
                        for t in (gov.get("resume_times") or [])
                        if now - t < 60.0
                    ]
                    if len(recent) >= 4:
                        _log.error("gemini resume rate-limited (%s)", reason)
                        return False
                    gov["resume_times"] = recent + [now]
                    gov["gemini_resuming"] = True
                    handle = (gov.get("resumption_handle") or "").strip() or None
                    handles: list[str | None] = [handle, None] if handle else [None]
                    try:
                        async with session_send_lock:
                            old_cm = live_cm.pop("cm", None)
                            if old_cm is not None:
                                try:
                                    await old_cm.__aexit__(None, None, None)
                                except Exception:
                                    _log.warning("gemini session close during resume (%s)", reason)
                            last_exc: Exception | None = None
                            for try_handle in handles:
                                history, post_call = load_session_context(runtime, session_ref["id"])
                                setup_instruction = build_live_voice_instruction(
                                    profile,
                                    history=history,
                                    dialect=live_dialect,
                                    post_call=post_call,
                                )
                                resume_handle = try_handle
                                if try_handle and history_poisoned_by_santai(history):
                                    resume_handle = None
                                    _log.info(
                                        "gemini resume without handle — santai loop in history"
                                    )
                                config = _live_connect_config(
                                    setup_instruction,
                                    voice_cfg,
                                    resumption_handle=resume_handle,
                                )
                                new_cm = client.aio.live.connect(model=model, config=config)
                                try:
                                    new_session = await new_cm.__aenter__()
                                except Exception as exc:
                                    last_exc = exc
                                    _log.warning(
                                        "gemini resume connect failed reason=%s handle=%s: %s",
                                        reason,
                                        bool(try_handle),
                                        exc,
                                    )
                                    await asyncio.sleep(0.3)
                                    continue
                                live_cm["cm"] = new_cm
                                session.bind(new_session)
                                gov["gemini_activity_open"] = False
                                gov["user_activity_open"] = False
                                gov["activity_end_for_asr"] = False
                                gov["awaiting_asr_recovery"] = False
                                gov["awaiting_turn_complete"] = False
                                gov["model_generating"] = False
                                gov["pending"] = False
                                gov["commit_scheduled"] = False
                                gov["gemini_connected_at"] = time.monotonic()
                                gov["last_gemini_send"] = time.monotonic()
                                gov["go_away_at"] = 0.0
                                gov["mic_pacing_reset"] = True
                                gov["accept_mic"] = True
                                gov["ready_for_next_utterance"] = True
                                yield_turn_to_user("gemini_resumed")
                                _log.info(
                                    "gemini live resumed (%s) handle=%s (messages=%s)",
                                    reason,
                                    "yes" if try_handle else "fresh",
                                    len(history),
                                )
                                enqueue_browser(
                                    {
                                        "type": "notice",
                                        "message": "Sesi voice dipulihkan — lanjutkan bicara.",
                                    }
                                )
                                return True
                            if last_exc is not None:
                                _log.exception("gemini live resume failed (%s)", reason)
                            return False
                    finally:
                        gov["gemini_resuming"] = False

            async def browser_sender() -> None:
                try:
                    while not stop.is_set():
                        try:
                            payload = await asyncio.wait_for(browser_out.get(), timeout=0.25)
                        except asyncio.TimeoutError:
                            continue
                        if payload is None:
                            break
                        await ws.send_json(payload)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _log.exception("browser sender failed")
                    stop.set()

            def persist_spoken_reply(text: str) -> None:
                stripped = (text or "").strip()
                if not stripped:
                    return

                async def _persist() -> None:
                    try:
                        await asyncio.to_thread(
                            runtime.record_spoken_reply, session_ref["id"], stripped
                        )
                    except Exception:
                        _log.exception("failed to persist spoken reply")

                asyncio.create_task(_persist())

            def enqueue_browser(payload: dict) -> None:
                try:
                    browser_out.put_nowait(payload)
                except asyncio.QueueFull:
                    # Prefer dropping oldest audio frames over blocking Gemini receive.
                    dropped = 0
                    while dropped < 8:
                        try:
                            old = browser_out.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        if old is None:
                            break
                        if isinstance(old, dict) and old.get("type") == "audio":
                            dropped += 1
                            continue
                        # Non-audio control message — put it back if possible.
                        try:
                            browser_out.put_nowait(old)
                        except asyncio.QueueFull:
                            pass
                        break
                    try:
                        browser_out.put_nowait(payload)
                    except asyncio.QueueFull:
                        _log.warning("browser_out full — dropping payload type=%s", payload.get("type"))

            def set_floor(speaker: str, *, reason: str = "") -> None:
                """WebSocket turn-taking — client UI follows this, not local playback guesses."""
                if not _take_floor(gov, speaker):
                    return
                enqueue_browser(_floor_event(speaker, reason=reason))
                _log.info("floor → %s (%s)", speaker, reason or "ws")

            def yield_turn_to_user(reason: str) -> None:
                now = time.monotonic()
                last_reason = gov.get("_last_yield_reason")
                last_at = float(gov.get("_last_yield_at") or 0.0)
                if reason in ("turn_complete", "natural_audio_done"):
                    if last_reason == reason and (now - last_at) < 1.0:
                        _log.info("skip duplicate yield_turn reason=%s", reason)
                        return
                    if gov.get("floor") == "user" and (now - last_at) < 2.0:
                        _log.info("skip duplicate yield — floor already user reason=%s", reason)
                        return
                gov["_last_yield_reason"] = reason
                gov["_last_yield_at"] = now
                if gov.get("natural_mode") and reason in (
                    "turn_complete",
                    "natural_audio_done",
                    "greeting_done",
                ):
                    gov["last_forward_at"] = 0.0
                set_floor("user", reason=reason)
                payload: dict = {"type": "turn_complete", "reason": reason}
                if should_play_laugh_track(gov, gov.get("dialect")):
                    payload["laugh_track"] = True
                    gov["laugh_track_pending"] = False
                if should_play_jedag_jedug(gov, gov.get("dialect")):
                    payload["jedag_jedug"] = True
                enqueue_browser(payload)

            def note_user_activity() -> None:
                gov["last_user_activity_at"] = time.monotonic()

            def call_duration_ms() -> int:
                started = gov.get("session_started_at")
                if isinstance(started, (int, float)):
                    return int((time.monotonic() - started) * 1000)
                return 0

            def build_live_call(
                *,
                status: str,
                end_reason: str | None = None,
                call_analysis: dict | None = None,
            ) -> dict:
                return build_call_object(
                    session_id=session_ref["id"],
                    agent_id=profile.preset_id,
                    call_status=status,
                    duration_ms=call_duration_ms(),
                    end_reason=end_reason,
                    voice_name=voice_cfg.voice_name,
                    language_code=voice_cfg.language_code,
                    call_analysis=call_analysis,
                )

            def schedule_webhook(event: str, call: dict) -> None:
                if not webhook_cfg.should_emit(event):
                    return

                async def _send() -> None:
                    result = await asyncio.to_thread(
                        deliver_webhook_event,
                        webhook_cfg,
                        event=event,
                        call=call,
                        dynamic_variables=dyn_vars,
                    )
                    if not result.get("ok") and not result.get("skipped"):
                        _log.warning("webhook delivery failed event=%s result=%s", event, result)

                asyncio.create_task(_send())

            async def end_call(reason: str, message: str | None = None) -> None:
                if stop.is_set():
                    return
                gov["call_end_reason"] = reason
                _log.info("ending live call reason=%s message=%r", reason, message)
                schedule_post_call_extraction(reason)
                if not gov.get("webhook_call_ended_sent"):
                    schedule_webhook(
                        "call_ended",
                        build_live_call(status="ended", end_reason=reason),
                    )
                    gov["webhook_call_ended_sent"] = True
                enqueue_browser(
                    {
                        "type": "call_ended",
                        "reason": reason,
                        "message": message or "",
                    }
                )
                stop.set()

            def schedule_post_call_extraction(end_reason: str) -> None:
                if gov.get("post_call_scheduled") or not post_call_cfg.enabled:
                    return
                gov["post_call_scheduled"] = True
                started = gov.get("session_started_at")
                duration_ms = 0
                if isinstance(started, (int, float)):
                    duration_ms = int((time.monotonic() - started) * 1000)
                sid = session_ref["id"]

                async def _run() -> None:
                    try:
                        result = await asyncio.to_thread(
                            extract_post_call_data,
                            runtime,
                            sid,
                            config=post_call_cfg,
                            end_reason=end_reason,
                            duration_ms=duration_ms,
                            api_key=api_key,
                            security_cfg=security_cfg,
                        )
                        if result:
                            data = result.get("data") or {}
                            enqueue_browser(
                                {
                                    "type": "post_call_data",
                                    "session_id": sid,
                                    "data": data,
                                    "model": result.get("model"),
                                }
                            )
                            schedule_webhook(
                                "call_analyzed",
                                build_live_call(
                                    status="ended",
                                    end_reason=end_reason,
                                    call_analysis=result.get("data") or {},
                                ),
                            )
                    except Exception:
                        _log.exception("post-call extraction task failed")

                asyncio.create_task(_run())

            async def commit_keypad_input(digits: str) -> None:
                cleaned = "".join(ch for ch in digits if ch in "0123456789#*")
                gov["keypad_buffer"] = ""
                task = gov.get("keypad_task")
                if task is not None and not task.done():
                    task.cancel()
                gov["keypad_task"] = None
                if not cleaned:
                    return
                note_user_activity()
                transcript = f"Keypad: {cleaned}"
                _log.info("keypad input committed: %r", cleaned)
                schedule_final_governance(transcript)

            async def handle_keypad_digit(digit: str) -> None:
                if not call_cfg.enable_keypad_detection:
                    return
                if digit not in "0123456789#*":
                    return
                note_user_activity()
                buf = (gov.get("keypad_buffer") or "") + digit
                gov["keypad_buffer"] = buf
                task = gov.get("keypad_task")
                if task is not None and not task.done():
                    task.cancel()
                done, payload = call_cfg.keypad_complete(buf, latest_digit=digit)
                if done:
                    await commit_keypad_input(payload)
                    return

                async def _timeout() -> None:
                    try:
                        await asyncio.sleep(call_cfg.keypad_timeout_ms / 1000.0)
                        pending = gov.get("keypad_buffer") or ""
                        await commit_keypad_input(pending)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        _log.exception("keypad timeout failed")

                gov["keypad_task"] = asyncio.create_task(_timeout())

            def emit_latency(phase: str, *, turn_id: int | None = None, extra: dict | None = None) -> None:
                tid = turn_id if turn_id is not None else int(gov.get("_latency_turn_id", 0))
                metrics = _build_latency_metrics(gov, turn_id=tid, phase=phase, extra=extra)
                if len(metrics) <= 2:
                    return
                enqueue_browser({"type": "latency", "metrics": metrics})
                _log.info("turn latency %s", json.dumps(metrics, ensure_ascii=False))

            def note_forwarded_audio(*, greeting: bool = False) -> None:
                set_floor("agent", reason="audio")
                marks = gov.setdefault("_latency_marks", {})
                now = time.monotonic()
                if greeting or gov.get("greeting_phase"):
                    if marks.get("greeting_latency_logged"):
                        return
                    _latency_mark(gov, "greeting_first_audio", now=now)
                    _latency_mark(gov, "first_audio", now=now)
                    emit_latency("greeting", turn_id=0)
                    marks["greeting_latency_logged"] = True
                    return
                turn_id = int(gov.get("_latency_turn_id", 0))
                if marks.get("response_latency_logged_turn") == turn_id:
                    return
                if "first_audio" not in marks:
                    _latency_mark(gov, "first_audio", now=now)
                extra: dict = {}
                reason = gov.get("_last_commit_reason")
                if reason:
                    extra["commit_reason"] = reason
                emit_latency(
                    "turn_response",
                    turn_id=turn_id,
                    extra=extra or None,
                )
                marks["response_latency_logged_turn"] = turn_id

            def drain_mic_queue(reason: str) -> None:
                dropped = 0
                while True:
                    try:
                        audio_queue.get_nowait()
                        dropped += 1
                    except asyncio.QueueEmpty:
                        break
                if dropped:
                    _log.info("drained %s leftover mic chunks (%s)", dropped, reason)

            async def send_activity_start(*, user: bool = True, opening_rms: float | None = None) -> bool:
                deferred_steer = gov.get("natural_mode") and gov.get("conv_steer_deferred")
                if deferred_steer:
                    gov["conv_steer_deferred"] = False
                if not _is_natural_s2s(gov):
                    if gov.get("awaiting_turn_complete"):
                        _log.info("activity_start deferred — awaiting steered turn_complete")
                        return False
                    if gov.get("model_generating"):
                        _log.info("activity_start deferred — model still generating")
                        return False
                if gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery"):
                    _log.info("activity_start deferred — awaiting ASR recovery")
                    return False
                if _late_asr_task_pending(gov):
                    _log.info("activity_start deferred — late ASR governance pending")
                    return False
                if gov.get("gemini_activity_open"):
                    _log.info("activity_start skipped — gemini activity already open")
                    return True
                last_end = gov.get("last_activity_end_at")
                if isinstance(last_end, (int, float)):
                    gap_s = (
                        NATURAL_GAP_AFTER_END_S
                        if _is_natural_s2s(gov)
                        else MIN_GAP_AFTER_ACTIVITY_END_S
                    )
                    gap = gap_s - (time.monotonic() - last_end)
                    if gap > 0:
                        await asyncio.sleep(gap)
                async with session_send_lock:
                    await session.send_realtime_input(activity_start=types.ActivityStart())
                gov["gemini_activity_open"] = True
                gov["close_activity"] = False
                if user:
                    now = time.monotonic()
                    gov["user_activity_open"] = True
                    gov["vad_turn_active"] = True
                    gov["had_loud_speech"] = bool(
                        isinstance(opening_rms, (int, float))
                        and opening_rms >= _loud_mic_rms(gov)
                    )
                    gov["turn_peak_mic_rms"] = (
                        float(opening_rms) if isinstance(opening_rms, (int, float)) else 0.0
                    )
                    gov["activity_started_at"] = now
                    gov["last_loud_mic_at"] = now
                    gov["commit_scheduled"] = False
                    gov["asr_finished"] = False
                    gov["activity_end_for_asr"] = False
                    gov["activity_end_for_asr_at"] = 0.0
                    gov["awaiting_asr_recovery"] = False
                    gov["recovery_mic_buffer"] = []
                    gov["recovery_mic_pending"] = []
                    gov["flush_asr_after_send"] = False
                    gov["partial_stable_text"] = ""
                    gov["partial_stable_since"] = 0.0
                    gov["first_partial_at"] = 0.0
                    gov["partial_text"] = ""
                    gov["last_user_transcript"] = ""
                    gov["stray_abort_sent"] = False
                    gov["ignore_model_audio"] = False
                    gov["natural_endpoint_sent"] = False
                    set_floor("user", reason="user_activity")
                if deferred_steer:
                    asyncio.create_task(
                        _flush_pending_conversation_steer(
                            gov,
                            session,
                            send_lock=session_send_lock,
                            reason="post_activity_start",
                        )
                    )
                return True

            async def send_activity_end() -> None:
                if not gov.get("gemini_activity_open"):
                    return
                async with session_send_lock:
                    await session.send_realtime_input(activity_end=types.ActivityEnd())
                gov["gemini_activity_open"] = False
                gov["user_activity_open"] = False
                gov["close_activity"] = False
                gov["last_activity_end_at"] = time.monotonic()
                gov["last_gemini_send"] = time.monotonic()
                # Keep floor=user until playable agent audio — muting here cuts the user off.

            def release_recovery_mic_buffer(reason: str) -> None:
                _schedule_recovery_mic_release(gov, reason)

            async def maybe_complete_asr_flush() -> None:
                """Send activity_end after recovered speech is forwarded — never wait on live mic."""
                if not gov.get("flush_asr_after_send"):
                    return
                if _recovery_drip_pending(gov):
                    started = gov.get("flush_asr_started_at")
                    if not isinstance(started, (int, float)) or (time.monotonic() - started) < 1.2:
                        return
                    _log.warning("ASR flush timeout — closing activity with drip still pending")
                gov["flush_asr_after_send"] = False
                gov["flush_asr_started_at"] = 0.0
                if gov.get("gemini_activity_open"):
                    await send_activity_end()
                _mark_asr_recovery(gov)
                _log.info(
                    "flush ASR — activity_end after recovered speech (silence=%sms)",
                    gov.get("voice_pause_ms"),
                )

            async def gemini_audio_sender() -> None:
                """Stream mic PCM into an open Persona-controlled activity."""
                sent_to_gemini = 0
                next_send = time.monotonic()
                try:
                    while not stop.is_set():
                        _drip_recovery_mic(gov, audio_queue)
                        while audio_queue.qsize() > MAX_AUDIO_QUEUE_CHUNKS:
                            try:
                                audio_queue.get_nowait()
                                _log.warning("dropped stale mic chunk (queue backlog)")
                            except asyncio.QueueEmpty:
                                break

                        try:
                            pcm = await asyncio.wait_for(audio_queue.get(), timeout=0.25)
                        except asyncio.TimeoutError:
                            await maybe_complete_asr_flush()
                            continue
                        if pcm is None:
                            break

                        if gov.pop("mic_pacing_reset", False):
                            next_send = time.monotonic()
                            _log.info("gemini mic pacing reset — real-time stream started")

                        rms = _pcm_rms(pcm)
                        now = time.monotonic()
                        _note_mic_rms(gov, rms, now=now)

                        if _should_buffer_mic(gov):
                            _append_recovery_mic(gov, pcm)
                            continue

                        if _should_open_user_activity(gov, rms, now=now):
                            if now < next_send:
                                await asyncio.sleep(next_send - now)
                            opened = await send_activity_start(opening_rms=rms)
                            if not opened:
                                _append_recovery_mic(gov, pcm)
                                continue
                            async with session_send_lock:
                                await session.send_realtime_input(
                                    audio=types.Blob(
                                        data=pcm, mime_type="audio/pcm;rate=16000"
                                    )
                                )
                            gov["last_gemini_send"] = time.monotonic()
                            sent_to_gemini += 1
                            _log.info(
                                "user activity started — mic chunk #%s rms=%.4f",
                                sent_to_gemini,
                                rms,
                            )
                            next_send = time.monotonic() + MIC_CHUNK_DURATION_S
                            if gov.pop("close_activity", False):
                                await send_activity_end()
                            await maybe_complete_asr_flush()
                            continue

                        if not gov.get("gemini_activity_open"):
                            continue

                        now = time.monotonic()
                        if now < next_send:
                            await asyncio.sleep(next_send - now)

                        async with session_send_lock:
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=pcm, mime_type="audio/pcm;rate=16000"
                                )
                            )
                        gov["last_gemini_send"] = time.monotonic()
                        sent_to_gemini += 1
                        if sent_to_gemini in (1, 10, 50) or sent_to_gemini % 100 == 0:
                            _log.info(
                                "gemini mic sent chunk #%s (%s bytes, rms=%.4f)",
                                sent_to_gemini,
                                len(pcm),
                                rms,
                            )
                        next_send += MIC_CHUNK_DURATION_S
                        if time.monotonic() - next_send > 1.0:
                            next_send = time.monotonic()
                        if gov.pop("close_activity", False):
                            await send_activity_end()
                        await maybe_complete_asr_flush()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if stop.is_set():
                        return
                    if (
                        gov.get("gemini_resuming") or _is_gemini_goaway_error(exc)
                    ) and await resume_gemini("send_1008"):
                        return await gemini_audio_sender()
                    _log.exception("gemini audio sender failed")
                    enqueue_browser(
                        {
                            "type": "error",
                            "message": _browser_gemini_error(exc),
                        }
                    )
                    stop.set()

            async def gemini_keepalive() -> None:
                """Send silent PCM during idle gaps — no activity_start/end (avoids WS 1007)."""
                try:
                    while not stop.is_set():
                        await asyncio.sleep(2.0)
                        if stop.is_set() or not gov.get("accept_mic"):
                            continue
                        if gov.get("greeting_phase") or gov.get("awaiting_turn_complete"):
                            continue
                        if (
                            gov.get("gemini_activity_open")
                            or gov.get("user_activity_open")
                            or gov.get("activity_end_for_asr")
                            or gov.get("awaiting_asr_recovery")
                        ):
                            continue
                        idle = time.monotonic() - gov["last_gemini_send"]
                        if idle < GEMINI_KEEPALIVE_IDLE_S:
                            continue
                        async with session_send_lock:
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=GEMINI_KEEPALIVE_PCM,
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                        gov["last_gemini_send"] = time.monotonic()
                        _log.debug("gemini keepalive pcm (idle %.1fs)", idle)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if stop.is_set():
                        return
                    if (
                        gov.get("gemini_resuming") or _is_gemini_goaway_error(exc)
                    ) and await resume_gemini("keepalive_1008"):
                        return await gemini_keepalive()
                    _log.exception("gemini keepalive failed")
                    stop.set()

            async def apply_governance(
                transcript: str, *, partial: bool = False, persist: bool = True
            ) -> None:
                """Run Persona BDV, inject constraints into the open activity, then activity_end."""
                key = session_ref["id"]
                normalized = transcript.strip()
                if not normalized:
                    return
                thread = load_session_messages(runtime, key)
                post_call = load_session_post_call(runtime, key)
                if partial:
                    if gov.get("natural_mode"):
                        gov["partial_text"] = normalized
                        return
                    if normalized == gov["partial_text"]:
                        return
                    gov["partial_text"] = normalized
                    overrides = session_overrides(runtime, key)
                    output = await asyncio.to_thread(
                        runtime.process_turn,
                        key,
                        normalized,
                        persist=False,
                        overrides=overrides,
                        channel="voice",
                        generate_text=False,
                        voice_pause_ms=gov.get("voice_pause_ms") or None,
                    )
                    decision = decide_live_action(output)
                    plan = plan_live_governance(
                        output, decision, profile, history=thread, live_mode=live_mode,
                        dialect=live_dialect, post_call=post_call,
                    )
                    payload = governance_payload(decision, plan=plan, partial=True)
                    if voice_cfg.should_emit_backchannel(normalized) and decision.bdv == "ACK_ONLY":
                        payload["backchannel"] = True
                    enqueue_browser(payload)
                    return

                if _last_transcript.get(key) == normalized:
                    if gov.get("gemini_activity_open"):
                        await send_activity_end()
                    gov["commit_scheduled"] = False
                    gov["ready_for_next_utterance"] = True
                    gov["accept_mic"] = True
                    gov["awaiting_turn_complete"] = False
                    yield_turn_to_user("duplicate_transcript")
                    return

                if gov.get("natural_mode"):
                    _last_transcript[key] = normalized
                    gov["last_governed_transcript"] = normalized
                    await asyncio.to_thread(
                        _natural_persist_user_turn,
                        runtime,
                        key,
                        normalized,
                    )
                    gov["commit_scheduled"] = False
                    gov["ready_for_next_utterance"] = True
                    if gov.get("final_scheduled_for") == normalized:
                        gov["final_scheduled_for"] = ""
                    return

                web_steer_extra = ""
                if (
                    not gov.get("natural_mode")
                    and not gov.get("greeting_phase")
                    and needs_live_web_search(normalized)
                ):
                    try:
                        web_ctx = await asyncio.wait_for(
                            fetch_live_web_context(normalized, api_key),
                            timeout=8.0,
                        )
                        if web_ctx:
                            web_steer_extra = format_web_context_for_steer(
                                web_ctx, dialect=live_dialect
                            )
                            _log.info(
                                "live web search injected preview=%r",
                                web_ctx[:120],
                            )
                    except asyncio.TimeoutError:
                        _log.warning("live web search timeout — skip inject")
                    except Exception as exc:
                        _log.warning("live web search error — skip inject: %s", exc)

                async with gov["lock"]:
                    _latency_mark(gov, "governance_start")
                    _last_transcript[key] = normalized
                    gov["last_governed_transcript"] = normalized

                    output = await asyncio.to_thread(
                        runtime.process_turn,
                        key,
                        normalized,
                        persist=persist,
                        channel="voice",
                        response_policy=live_response_policy(profile),
                        generate_text=False,
                        voice_pause_ms=gov.get("voice_pause_ms") or None,
                    )
                    decision = decide_live_action(output)
                    plan = plan_live_governance(
                        output,
                        decision,
                        profile,
                        history=load_session_messages(runtime, key) or thread,
                        live_mode=live_mode,
                        dialect=live_dialect,
                        post_call=load_session_post_call(runtime, key) or post_call,
                    )

                    if gov.get("natural_mode") and plan.steer_mode == LiveSteerMode.ALLOW:
                        _log.info(
                            "natural S2S — memory-only governance (no steer inject)"
                        )
                        enqueue_browser(governance_payload(decision, plan=plan))
                        gov["commit_scheduled"] = False
                        gov["ready_for_next_utterance"] = True
                        if gov.get("final_scheduled_for") == normalized:
                            gov["final_scheduled_for"] = ""
                        _last_transcript[key] = normalized
                        _latency_mark(gov, "governance_done")
                        return

                    if plan.steer_mode == LiveSteerMode.ALLOW:
                        if web_steer_extra:
                            if _agent_reply_already_started(gov):
                                _log.info(
                                    "skip web steer — agent reply already in flight"
                                )
                                web_steer_extra = ""
                            else:
                                await _steer_gemini_session(
                                    session, web_steer_extra, send_lock=session_send_lock
                                )
                                gov["last_gemini_send"] = time.monotonic()
                        flushed = _apply_natural_allow(gov)
                        for chunk in flushed:
                            enqueue_browser(
                                {
                                    "type": "audio",
                                    "mime": "audio/pcm;rate=24000",
                                    "data": base64.b64encode(chunk).decode("ascii"),
                                }
                            )
                        if flushed:
                            note_forwarded_audio(greeting=False)
                        enqueue_browser(governance_payload(decision, plan=plan))
                        if not gov.get("awaiting_turn_complete"):
                            yield_turn_to_user("allow_complete")
                        _latency_mark(gov, "governance_done")
                        _log.info(
                            "natural S2S allow bdv=%s — play buffered=%s wait_complete=%s",
                            decision.bdv,
                            len(flushed),
                            gov.get("awaiting_turn_complete"),
                        )
                        if gov.get("gemini_activity_open") and not _agent_reply_already_started(gov):
                            if gov.get("natural_endpoint_sent"):
                                _log.info("skip duplicate activity_end — natural endpoint already sent")
                            else:
                                await send_activity_end()
                                gov["last_gemini_send"] = time.monotonic()
                        return

                    gov["accept_mic"] = False
                    gov["pending"] = True
                    gov["mode"] = plan.steer_mode
                    gov["steer_applied"] = False
                    gov["play_steered"] = False
                    gov["ungoverned_complete"] = False
                    gov["user_activity_open"] = False
                    enqueue_browser(
                        {"type": "governance", "bdv": "pending"}
                    )

                    if not plan.steer_prompt:
                        _log.error("governance plan missing steer_prompt for bdv=%s", decision.bdv)
                        enqueue_browser(
                            {
                                "type": "error",
                                "message": "Persona governance: tidak ada directive untuk Gemini",
                            }
                        )
                        gov["pending"] = False
                        gov["commit_scheduled"] = False
                        gov["accept_mic"] = True
                        gov["ready_for_next_utterance"] = True
                        yield_turn_to_user("missing_steer")
                        await send_activity_end()
                        return

                    gov["mode"] = plan.steer_mode
                    gov["steer_applied"] = False

                    try:
                        in_activity = bool(gov.get("gemini_activity_open"))
                        steer_text = plan.steer_prompt or ""
                        engine_body = (plan.dynamic_instruction or steer_text).rstrip()
                        if web_steer_extra:
                            engine_body = f"{engine_body}\n\n{web_steer_extra}"
                        if (
                            not in_activity
                            and normalized
                            and plan.steer_mode == LiveSteerMode.ENGINE
                        ):
                            steer_text = build_engine_directive_for_transcript(
                                normalized, engine_body, dialect=live_dialect
                            )
                        elif web_steer_extra:
                            steer_text = engine_body
                        if in_activity:
                            await _steer_gemini_session(
                                session, steer_text, send_lock=session_send_lock
                            )
                        else:
                            # Post activity_end — text-only activity_start/end triggers 1007.
                            async with session_send_lock:
                                await session.send_realtime_input(text=steer_text)
                            gov["last_gemini_send"] = time.monotonic()
                            _log.info("steer delivered plain (no activity wrapper)")
                        pause_s = _bdv_pause_seconds(output)
                        if pause_s > 0:
                            await asyncio.sleep(pause_s)
                        # Open the gate before activity_end so the first steered PCM is not dropped.
                        gov["steer_applied"] = True
                        gov["awaiting_steered_turn"] = True
                        gov["steered_audio_seen"] = False
                        gov["ready_for_next_utterance"] = False
                        gov["play_steered"] = True
                        _mark_awaiting_turn_complete(gov)
                        if in_activity:
                            await send_activity_end()
                            gov["last_gemini_send"] = time.monotonic()
                        _latency_mark(gov, "governance_done")
                    except Exception as steer_exc:
                        _log.exception("Gemini steer failed for bdv=%s", decision.bdv)
                        gov["mode"] = LiveSteerMode.ALLOW
                        gov["steer_applied"] = False
                        enqueue_browser(
                            {
                                "type": "error",
                                "message": f"Governance steer gagal: {steer_exc}",
                            }
                        )
                        gov["pending"] = False
                        gov["commit_scheduled"] = False
                        gov["accept_mic"] = True
                        gov["ready_for_next_utterance"] = True
                        yield_turn_to_user("steer_failed")
                        try:
                            await send_activity_end()
                        except Exception:
                            pass
                        return

                    payload = governance_payload(decision, plan=plan)
                    if (
                        voice_cfg.should_emit_backchannel(normalized)
                        and decision.bdv == "ACK_ONLY"
                        and decision.text
                    ):
                        payload["backchannel"] = True
                    enqueue_browser(payload)
                    _log.info(
                        "persona-first turn raw_bdv=%s effective_bdv=%s steer=%s play=%s pause_ms=%s",
                        output.trace.raw_bdv_action if output.trace else None,
                        decision.bdv,
                        plan.steer_mode.value,
                        gov.get("play_steered"),
                        gov.get("voice_pause_ms"),
                    )

                    gov["mode"] = plan.steer_mode
                    gov["pending"] = False
                    gov["commit_scheduled"] = False

            def cut_agent_audio(reason: str) -> None:
                dropped = _drop_queued_audio(browser_out)
                set_floor("user", reason=reason)
                enqueue_browser({"type": "interrupt"})
                _log.info("%s — flushed agent audio (dropped %s frames)", reason, dropped)

            def schedule_final_governance(transcript: str, *, persist: bool = True) -> str:
                """Non-blocking: keep session.receive() alive for Gemini keepalive."""
                normalized = transcript.strip()
                key = session_ref["id"]
                if not _should_govern_transcript(normalized):
                    _log.info("ignore weak transcript for governance: %r", normalized)
                    return "ignored"
                if _is_voice_filler(normalized):
                    _log.info("ignore voice filler: %r", normalized)
                    return "ignored"
                if _should_drop_spurious_asr(gov, normalized):
                    return "ignored"
                if gov.get("natural_mode") and _last_transcript.get(key) == normalized:
                    return "declined"
                if _answer_in_flight(gov) and normalized:
                    if _should_drop_spurious_asr(gov, normalized):
                        _log.info(
                            "ignore queued echo/spurious while answer plays: %r",
                            normalized[:80],
                        )
                        return "ignored"
                    gov["queued_transcript"] = normalized
                    _log.info("queue transcript while answer plays: %r", normalized)
                    return "queued"
                if not _should_start_final_governance(gov, normalized, _last_transcript, key):
                    return "declined"
                _clear_asr_recovery(gov)
                _reset_vad_turn(gov)
                gov["queued_transcript"] = ""
                gov["final_scheduled_for"] = normalized
                gov["fallback_final_scheduled"] = True
                if not gov.get("natural_mode"):
                    gov["ready_for_next_utterance"] = False
                persist_turn = persist
                partial_task = gov.get("partial_task")
                if partial_task and not partial_task.done():
                    partial_task.cancel()
                gov["partial_text"] = ""

                async def _run() -> None:
                    try:
                        gov["activity_end_for_asr"] = False
                        gov["activity_end_for_asr_at"] = 0.0
                        await apply_governance(transcript, partial=False, persist=persist_turn)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        _log.exception("final governance failed")
                    finally:
                        gov["commit_scheduled"] = False
                        if gov.get("final_scheduled_for") == normalized:
                            gov["final_scheduled_for"] = ""

                # #region agent log
                _debug_log(
                    "gemini_live_bridge.py:schedule_final_governance",
                    "final governance scheduled",
                    {
                        "transcript_len": len(normalized),
                        "transcript_preview": normalized[:80],
                        "latest": _latest_governance_transcript(gov)[:80],
                    },
                    hypothesis_id="H3",
                )
                # #endregion
                gov["final_task"] = asyncio.create_task(_run())
                return "scheduled"

            def schedule_partial_governance(text: str) -> None:
                """Track partial ASR only — BDV runs once via persona_turn_committer."""
                normalized = text.strip()
                if _is_voice_filler(normalized) or _should_drop_spurious_asr(gov, normalized):
                    return
                if len(normalized) < _partial_min_chars(gov):
                    return
                gov["partial_text"] = normalized
                _update_partial_stability(gov, normalized)

            def schedule_late_asr_governance(text: str) -> None:
                """ASR final arrived after flush/abandon — debounce then run full turn."""
                normalized = text.strip()
                if not normalized or len(normalized) < _partial_min_chars(gov):
                    return
                if _is_voice_filler(normalized) or _should_drop_spurious_asr(gov, normalized):
                    return
                if not gov.get("asr_finished"):
                    return
                key = session_ref["id"]
                if _last_transcript.get(key) == normalized:
                    return
                if not _should_schedule_late_asr(gov):
                    return
                if (
                    gov.get("user_activity_open")
                    or gov.get("gemini_activity_open")
                    or _answer_in_flight(gov)
                    or gov.get("awaiting_turn_complete")
                ):
                    return
                task = gov.get("late_asr_task")
                if task is not None and not task.done():
                    task.cancel()

                async def _debounced() -> None:
                    try:
                        await asyncio.sleep(PARTIAL_DEBOUNCE_S)
                        if (
                            gov.get("user_activity_open")
                            or gov.get("gemini_activity_open")
                            or _answer_in_flight(gov)
                            or gov.get("awaiting_turn_complete")
                        ):
                            return
                        if not _should_schedule_late_asr(gov):
                            return
                        latest = _latest_governance_transcript(gov)
                        if not latest:
                            return
                        _clear_asr_recovery(gov)
                        gov["_last_commit_reason"] = "late_asr_final"
                        _latency_mark(gov, "user_commit")
                        _next_turn_id(gov)
                        _log.info(
                            "late ASR final after activity closed — governing: %r",
                            latest,
                        )
                        # #region agent log
                        _debug_log(
                            "gemini_live_bridge.py:schedule_late_asr_governance",
                            "late ASR final commit",
                            {"transcript_preview": latest[:80]},
                            hypothesis_id="H3",
                        )
                        # #endregion
                        gov["voice_pause_ms"] = 0
                        schedule_final_governance(latest)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        _log.exception("late ASR governance failed")

                gov["late_asr_task"] = asyncio.create_task(_debounced())

            async def send_opening_greeting() -> None:
                prompt = opening_prompt
                delay_s = voice_cfg.begin_message_delay_ms / 1000.0
                try:
                    try:
                        await asyncio.wait_for(client_ready.wait(), timeout=12.0)
                    except asyncio.TimeoutError:
                        _log.warning("client_ready timeout — sending greeting anyway")
                    if delay_s > 0:
                        await asyncio.sleep(delay_s)
                    if not prompt:
                        gov["accept_mic"] = True
                        gov["mic_pacing_reset"] = True
                        gov["ready_for_next_utterance"] = True
                        set_floor("user", reason="mic_enable")
                        enqueue_browser({"type": "mic_enable"})
                        pending = pending_user_utterance(prior_messages)
                        if pending:
                            _log.info(
                                "unanswered history on connect (wait for fresh mic): %r",
                                pending,
                            )
                        return
                    async with session_send_lock:
                        # Gemini 3.1 Live rejects text-only activity turns (1007
                        # Precondition check failed). Steer greeting as plain
                        # realtime text — same as text-only nudge, no wrapper.
                        await session.send_realtime_input(text=prompt)
                    gov["last_gemini_send"] = time.monotonic()
                    set_floor("agent", reason="greeting")
                    _log.info(
                        "opening greeting sent after %sms delay",
                        voice_cfg.begin_message_delay_ms,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _log.exception("opening greeting failed")

            async def greeting_mic_fallback() -> None:
                try:
                    await asyncio.sleep(GREETING_MIC_FALLBACK_S)
                    if stop.is_set():
                        return
                    if gov.get("greeting_phase") and not gov.get("accept_mic"):
                        gov["greeting_phase"] = False
                        gov["accept_mic"] = True
                        gov["mode"] = _idle_steer_mode(gov)
                        gov["pending"] = False
                        gov["steer_applied"] = gov.get("natural_mode", False)
                        gov["mic_pacing_reset"] = True
                        gov["ready_for_next_utterance"] = True
                        _log.warning("greeting mic fallback — mic input enabled")
                        yield_turn_to_user("mic_fallback")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _log.exception("greeting mic fallback failed")

            def should_forward_audio() -> bool:
                return _should_forward_governed_audio(gov)

            async def client_to_gemini() -> None:
                try:
                    while not stop.is_set():
                        message = await ws.receive()
                        if message.get("type") == "websocket.disconnect":
                            stop.set()
                            break
                        text = message.get("text")
                        if not text:
                            continue
                        payload = json.loads(text)
                        kind = payload.get("type")
                        if kind == "stop":
                            stop.set()
                            break
                        if kind == "session" and payload.get("session_id"):
                            session_ref["id"] = str(payload["session_id"])
                            continue
                        if kind == "client_ready":
                            client_ready.set()
                            continue
                        if kind == "barge_in":
                            note_user_activity()
                            mark_user_speech_start(gov)
                            transcript = str(payload.get("transcript") or "").strip()
                            client_rms = not transcript
                            if not should_allow_barge_in(
                                gov,
                                transcript=transcript or None,
                                dialect=gov.get("dialect"),
                                client_rms=client_rms,
                            ):
                                _log.info(
                                    "smart barge-in rejected transcript=%r duration=%.2fs",
                                    transcript[:80] if transcript else "",
                                    speech_duration_s(gov),
                                )
                                clear_user_speech_start(gov)
                                continue
                            clear_user_speech_start(gov)
                            _apply_barge_in(gov, soft=True)
                            dropped = _drop_queued_audio(browser_out)
                            _log.info(
                                "soft barge-in — fade cut (dropped %s queued frames)",
                                dropped,
                            )
                            if gov.get("gemini_activity_open"):
                                await send_activity_end()
                            gov["mic_pacing_reset"] = True
                            set_floor("user", reason="barge_in")
                            enqueue_browser({"type": "mic_enable"})
                            continue
                        if kind == "keypad" and payload.get("digit"):
                            await handle_keypad_digit(str(payload["digit"]))
                            continue
                        if kind == "activity_end":
                            if gov.get("user_activity_open") and not gov.get("commit_scheduled"):
                                silence_s = voice_cfg.silence_duration_ms() / 1000.0
                                gov["last_loud_mic_at"] = time.monotonic() - silence_s
                            continue
                        if kind == "activity_start":
                            continue
                        if kind == "audio" and payload.get("data"):
                            if not gov.get("accept_mic") and not (
                                gov.get("user_activity_open") or gov.get("gemini_activity_open")
                            ):
                                continue
                            pcm = base64.b64decode(payload["data"])
                            if pcm:
                                gov["mic_chunks"] += 1
                                rms = _pcm_rms(pcm)
                                _note_mic_rms(gov, rms)
                                if gov.get("flush_asr_after_send"):
                                    _append_recovery_mic(gov, pcm)
                                    continue
                                if gov["mic_chunks"] in (1, 10, 50) or rms >= 0.02:
                                    _log.info(
                                        "client mic chunk #%s (%s bytes, rms=%.4f)",
                                        gov["mic_chunks"],
                                        len(pcm),
                                        rms,
                                    )
                                try:
                                    audio_queue.put_nowait(pcm)
                                except asyncio.QueueFull:
                                    try:
                                        audio_queue.get_nowait()
                                    except asyncio.QueueEmpty:
                                        pass
                                    try:
                                        audio_queue.put_nowait(pcm)
                                    except asyncio.QueueFull:
                                        pass
                except WebSocketDisconnect:
                    stop.set()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if not stop.is_set():
                        enqueue_browser({"type": "error", "message": str(exc)})
                    stop.set()

            async def gemini_to_client() -> None:
                """Read Gemini messages continuously (_receive, not receive() which stops per turn)."""
                audio_fwd = 0
                while not stop.is_set():
                    try:
                        msg = await session._receive()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        if stop.is_set():
                            return
                        if (
                            gov.get("gemini_resuming") or _is_gemini_goaway_error(exc)
                        ) and await resume_gemini("receive_1008"):
                            continue
                        enqueue_browser(
                            {"type": "error", "message": _browser_gemini_error(exc)}
                        )
                        stop.set()
                        return

                    update = getattr(msg, "session_resumption_update", None)
                    if update is not None:
                        _store_resumption_handle(gov, update)

                    go_away = getattr(msg, "go_away", None)
                    if go_away is not None:
                        _log.warning(
                            "gemini GoAway time_left=%s — resuming Live session",
                            getattr(go_away, "time_left", None),
                        )
                        gov["go_away_at"] = time.monotonic()
                        if not _live_session_idle(gov):
                            _log.warning(
                                "gemini GoAway while busy — waiting for idle before resume"
                            )
                            continue
                        if await resume_gemini("go_away"):
                            continue
                        enqueue_browser(
                            {
                                "type": "error",
                                "message": GEMINI_SESSION_EXPIRED_MSG,
                            }
                        )
                        stop.set()
                        return

                    sc = msg.server_content
                    if not sc:
                        continue

                    try:
                        if sc.interrupted:
                            _log.info(
                                "gemini interrupted flag — keeping playback (play=%s steered=%s mode=%s)",
                                gov.get("play_steered"),
                                gov.get("steer_applied"),
                                gov["mode"].value if hasattr(gov.get("mode"), "value") else gov.get("mode"),
                            )

                        if sc.model_turn:
                            pcm_parts = []
                            drop_leftover = bool(gov.get("ignore_model_audio"))
                            for part in sc.model_turn.parts or []:
                                blob = part.inline_data
                                if blob and blob.data:
                                    if drop_leftover or gov.get("user_activity_open"):
                                        continue
                                    if not _is_natural_s2s(gov):
                                        gov["model_generating"] = True
                                    pcm_parts.append((blob.data, blob.mime_type or "audio/pcm;rate=24000"))
                            if should_forward_audio():
                                if gov.get("awaiting_steered_turn"):
                                    gov["steered_audio_seen"] = True
                                buffered = [
                                    c
                                    for c in _flush_ungoverned_audio_buffer(gov)
                                    if _is_playable_pcm(c)
                                ]
                                if buffered:
                                    _log.info(
                                        "flush ungoverned audio buffer chunks=%s bytes=%s",
                                        len(buffered),
                                        sum(len(c) for c in buffered),
                                    )
                                noted_audio = False
                                for chunk in buffered:
                                    audio_fwd += 1
                                    gov["last_forward_at"] = time.monotonic()
                                    enqueue_browser(
                                        {
                                            "type": "audio",
                                            "mime": "audio/pcm;rate=24000",
                                            "data": base64.b64encode(chunk).decode("ascii"),
                                        }
                                    )
                                    if not noted_audio:
                                        note_forwarded_audio(greeting=gov.get("greeting_phase", False))
                                        noted_audio = True
                                for data, mime in pcm_parts:
                                    if not _is_playable_pcm(data):
                                        _log.info("skip tiny model pcm %s bytes", len(data))
                                        continue
                                    gov["last_forward_at"] = time.monotonic()
                                    audio_fwd += 1
                                    if audio_fwd <= 3 or audio_fwd % 10 == 0:
                                        _log.info(
                                            "forward model audio #%s %s bytes (mode=%s)",
                                            audio_fwd,
                                            len(data),
                                            gov["mode"].value,
                                        )
                                    enqueue_browser(
                                        {
                                            "type": "audio",
                                            "mime": mime,
                                            "data": base64.b64encode(data).decode("ascii"),
                                        }
                                    )
                                    if not noted_audio:
                                        note_forwarded_audio(
                                            greeting=gov.get("greeting_phase", False)
                                        )
                                        noted_audio = True
                            else:
                                held = 0
                                for data, _mime in pcm_parts:
                                    if _should_buffer_ungoverned_audio(gov):
                                        if _append_ungoverned_audio(gov, data):
                                            held += 1
                                        else:
                                            _log.warning(
                                                "ungoverned audio drop buffer overflow total_drops=%s",
                                                gov.get("ungoverned_audio_drops"),
                                            )
                                    else:
                                        gov["held_audio"] = (
                                            gov.get("held_audio", 0) + 1
                                        )
                                        held += 1
                                if held:
                                    if gov["held_audio"] <= 3 or gov["held_audio"] % 10 == 0:
                                        _log.info(
                                            "hold model audio while user speaking chunks=%s total=%s buffer_bytes=%s",
                                            held,
                                            gov["held_audio"],
                                            gov.get("ungoverned_audio_buffer_bytes", 0),
                                        )
                        if sc.output_transcription and sc.output_transcription.text:
                            spoken = sc.output_transcription.text.strip()
                            if spoken:
                                prev = (gov.get("assistant_text") or "").strip()
                                if not prev:
                                    gov["assistant_turn_observed"] = False
                                    gov["agent_reply_epoch"] = int(gov.get("agent_reply_epoch") or 0) + 1
                                gov["assistant_text"] = (
                                    f"{prev} {spoken}".strip() if prev else spoken
                                )
                                _append_assistant_echo_corpus(gov, spoken)
                            if should_forward_audio():
                                enqueue_browser(
                                    {
                                        "type": "transcript",
                                        "role": "assistant",
                                        "text": sc.output_transcription.text,
                                        "finished": sc.output_transcription.finished,
                                    }
                                )
                            if spoken and sc.output_transcription.finished:
                                gov["last_assistant_spoken"] = spoken

                        if sc.input_transcription and sc.input_transcription.text:
                            text = sc.input_transcription.text.strip()
                            if text and not _should_accept_input_transcription(gov):
                                _log.info(
                                    "stale ASR ignored (no open activity): %r",
                                    text,
                                )
                            elif text:
                                if _should_drop_spurious_asr(gov, text):
                                    continue
                                text = normalize_papua_transcript(text, dialect=gov.get("dialect"))
                                note_user_activity()
                                text = _lock_asr_recovery_partial(gov, text)
                                gov["last_transcript_at"] = time.monotonic()
                                if text != gov.get("last_user_transcript"):
                                    gov["last_user_transcript"] = text
                                    mark_humor_turn(gov, text)
                                    if gov.get("ready_for_next_utterance"):
                                        gov["fallback_final_scheduled"] = False
                                if not sc.input_transcription.finished:
                                    _update_partial_stability(gov, text)
                                    gov["partial_text"] = text
                                    _log.info("user transcript partial: %r", text)
                                enqueue_browser(
                                    {
                                        "type": "transcript",
                                        "role": "user",
                                        "text": text,
                                        "finished": sc.input_transcription.finished,
                                    }
                                )
                                if not gov.get("greeting_phase"):
                                    if sc.input_transcription.finished:
                                        gov["asr_finished"] = True
                                        _log.info(
                                            "user transcript final: %r",
                                            text,
                                        )
                                        if gov.get("natural_mode") and text.strip():
                                            conv = gov.get("conv_ctrl")
                                            if isinstance(conv, ConversationController):
                                                conv.observe_user_turn(text.strip())
                                            flow = gov.get("flow_ctrl")
                                            if isinstance(flow, ConversationFlowController):
                                                flow.on_user_final(text.strip())
                                            if analyze_user_turn(text.strip()).intent == "santai":
                                                mark_block_santai_reply(gov)
                                            _reset_vad_turn(gov)
                                            gov["ready_for_next_utterance"] = True
                                            gov["user_activity_open"] = False
                                            gov["natural_endpoint_sent"] = True
                                            if gov.get("gemini_activity_open"):
                                                if _agent_reply_already_started(gov):
                                                    _log.info(
                                                        "natural ASR final — skip activity_end, agent replying"
                                                    )
                                                else:
                                                    await send_activity_end()
                                                    gov["last_gemini_send"] = time.monotonic()
                                                    _log.info(
                                                        "natural immediate activity_end %r",
                                                        text[:80],
                                                    )
                                                    asyncio.create_task(
                                                        _schedule_pre_turn_loop_nudge(
                                                            gov,
                                                            session,
                                                            send_lock=session_send_lock,
                                                        )
                                                    )
                                            asyncio.create_task(
                                                apply_governance(
                                                    text.strip(),
                                                    partial=False,
                                                    persist=True,
                                                )
                                            )
                                        elif _should_schedule_late_asr(gov):
                                            schedule_late_asr_governance(text)
                                    else:
                                        schedule_partial_governance(text)
                            elif not text:
                                enqueue_browser(
                                    {
                                        "type": "transcript",
                                        "role": "user",
                                        "text": sc.input_transcription.text,
                                        "finished": sc.input_transcription.finished,
                                    }
                                )

                        if sc.turn_complete:
                            was_greeting = gov.get("greeting_phase")
                            if was_greeting:
                                _clear_assistant_transcript_buffer(gov)
                                gov["greeting_phase"] = False
                                gov["accept_mic"] = True
                                gov["mic_pacing_reset"] = True
                                gov["mode"] = _idle_steer_mode(gov)
                                gov["steer_applied"] = gov.get("natural_mode", False)
                                gov["awaiting_steered_turn"] = False
                                gov["steered_audio_seen"] = False
                                gov["ready_for_next_utterance"] = True
                                gov["model_generating"] = False
                                _log.info("greeting turn_complete — mic input enabled")
                                greeting_fallback = gov.get("greeting_fallback_task")
                                if greeting_fallback is not None and not greeting_fallback.done():
                                    greeting_fallback.cancel()
                                yield_turn_to_user("greeting_done")
                                continue
                            if gov.get("activity_end_for_asr") or gov.get("awaiting_asr_recovery"):
                                _clear_assistant_transcript_buffer(gov)
                                _log.info(
                                    "spontaneous turn_complete during ASR recovery — keep buffered reply"
                                )
                                gov["recovery_generation_complete"] = True
                                gov["model_generating"] = False
                                gov["held_audio"] = 0
                                gov["stray_abort_sent"] = False
                                pending = (
                                    (gov.get("asr_recovery_partial") or "").strip()
                                    or _latest_governance_transcript(gov)
                                )
                                key = session_ref["id"]
                                if (
                                    pending
                                    and pending != _last_transcript.get(key)
                                    and not _answer_in_flight(gov)
                                    and not gov.get("natural_mode")
                                ):
                                    gov["asr_finished"] = True
                                    schedule_final_governance(pending)
                                else:
                                    _clear_asr_recovery(gov)
                                    gov["recovery_generation_complete"] = False
                                    gov["ready_for_next_utterance"] = True
                                    gov["accept_mic"] = True
                                    gov["commit_scheduled"] = False
                                continue
                            if (
                                gov.get("stray_abort_sent")
                                and not gov.get("awaiting_steered_turn")
                                and not gov.get("steered_audio_seen")
                            ):
                                _clear_assistant_transcript_buffer(gov)
                                gov["stray_abort_sent"] = False
                                gov["held_audio"] = 0
                                gov["awaiting_turn_complete"] = False
                                gov["accept_mic"] = True
                                gov["ready_for_next_utterance"] = True
                                release_recovery_mic_buffer("stray_abort_turn_complete")
                                yield_turn_to_user("stray_abort")
                                _log.info(
                                    "stray abort turn_complete — mic reopened, ASR state kept"
                                )
                                continue
                            if gov.get("user_activity_open") or gov.get("commit_scheduled"):
                                if gov.get("awaiting_turn_complete"):
                                    if gov.get("natural_mode"):
                                        _log.info(
                                            "natural turn_complete during commit — full reset"
                                        )
                                        gov["commit_scheduled"] = False
                                        gov["model_generating"] = False
                                        gov["pending"] = False
                                        _clear_steered_turn_state(gov)
                                        gov["ready_for_next_utterance"] = True
                                        gov["accept_mic"] = True
                                        gov["mic_pacing_reset"] = True
                                        gov["last_turn_complete_at"] = time.monotonic()
                                        gov["asr_finished"] = False
                                        gov["partial_text"] = ""
                                        gov["partial_stable_text"] = ""
                                        gov["partial_stable_since"] = 0.0
                                        gov["first_partial_at"] = 0.0
                                        gov["held_audio"] = 0
                                        gov["stray_abort_sent"] = False
                                        _clear_ungoverned_audio_buffer(gov)
                                        drain_mic_queue("natural_turn_complete")
                                        release_recovery_mic_buffer("natural_turn_complete")
                                        _last_transcript.pop(session_ref["id"], None)
                                        await _on_safe_turn_boundary(
                                            gov,
                                            session,
                                            reason="turn_complete",
                                            send_lock=session_send_lock,
                                            yield_turn=yield_turn_to_user,
                                            persist=persist_spoken_reply,
                                        )
                                    else:
                                        _log.info(
                                            "finalize steered turn during user activity (leftover turn_complete)"
                                        )
                                        _clear_steered_turn_state(gov)
                                        gov["accept_mic"] = True
                                else:
                                    pending = _latest_governance_transcript(gov)
                                    key = session_ref["id"]
                                    already = _last_transcript.get(key)
                                    if (
                                        pending
                                        and pending != already
                                        and not _answer_in_flight(gov)
                                        and gov.get("ready_for_next_utterance", True)
                                        and not (
                                            gov.get("natural_mode")
                                            and _agent_reply_already_started(gov)
                                        )
                                    ):
                                        _log.info(
                                            "turn_complete commit pending partial: %r",
                                            pending,
                                        )
                                        # #region agent log
                                        _debug_log(
                                            "gemini_live_bridge.py:turn_complete",
                                            "commit on turn_complete",
                                            {
                                                "pending": pending[:80],
                                                "asr_finished": gov.get("asr_finished"),
                                            },
                                            hypothesis_id="H1",
                                        )
                                        # #endregion
                                        gov["asr_finished"] = True
                                        schedule_final_governance(pending)
                                    else:
                                        _log.info(
                                            "ignore leftover turn_complete during user activity"
                                        )
                                continue
                            if gov.get("pending"):
                                _clear_assistant_transcript_buffer(gov)
                                gov["ungoverned_complete"] = True
                                _log.info("ungoverned turn_complete while governance pending")
                                continue
                            gov["model_generating"] = False
                            gov["recovery_generation_complete"] = False
                            gov["mode"] = _idle_steer_mode(gov)
                            gov["pending"] = False
                            gov["steer_applied"] = bool(gov.get("natural_mode"))
                            gov["awaiting_steered_turn"] = False
                            gov["steered_audio_seen"] = False
                            gov["play_steered"] = False
                            gov["ungoverned_complete"] = False
                            gov["fallback_final_scheduled"] = False
                            gov["awaiting_turn_complete"] = False
                            gov["ready_for_next_utterance"] = True
                            gov["accept_mic"] = True
                            gov["mic_pacing_reset"] = True
                            gov["last_turn_complete_at"] = time.monotonic()
                            gov["asr_finished"] = False
                            gov["last_user_transcript"] = ""
                            gov["partial_text"] = ""
                            gov["partial_stable_text"] = ""
                            gov["partial_stable_since"] = 0.0
                            gov["first_partial_at"] = 0.0
                            gov["held_audio"] = 0
                            gov["stray_abort_sent"] = False
                            _clear_ungoverned_audio_buffer(gov)
                            drain_mic_queue("turn_complete")
                            release_recovery_mic_buffer("turn_complete")
                            _last_transcript.pop(session_ref["id"], None)
                            await _on_safe_turn_boundary(
                                gov,
                                session,
                                reason="turn_complete",
                                send_lock=session_send_lock,
                                yield_turn=yield_turn_to_user,
                                persist=persist_spoken_reply,
                            )
                            queued = (gov.get("queued_transcript") or "").strip()
                            gov["queued_transcript"] = ""
                            if queued:
                                if gov.get("natural_mode"):
                                    _log.info(
                                        "natural S2S — drop queued transcript (avoid double): %r",
                                        queued[:80],
                                    )
                                elif _should_drop_spurious_asr(gov, queued):
                                    _log.info(
                                        "dropped queued echo/spurious after answer: %r",
                                        queued[:80],
                                    )
                                elif _last_transcript.get(session_ref["id"]) == queued:
                                    _log.info(
                                        "dropped queued duplicate after answer: %r",
                                        queued[:80],
                                    )
                                else:
                                    _log.info(
                                        "draining queued transcript after answer: %r",
                                        queued,
                                    )
                                    schedule_final_governance(queued)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        if stop.is_set():
                            return
                        if (
                            gov.get("gemini_resuming") or _is_gemini_goaway_error(exc)
                        ) and await resume_gemini("process_1008"):
                            continue
                        enqueue_browser(
                            {"type": "error", "message": _browser_gemini_error(exc)}
                        )
                        stop.set()
                        return

            async def close_silent_user_activity() -> None:
                """Drop a VAD/ASR miss quietly — no DEFER bubble or steer noise."""
                gov["commit_scheduled"] = True
                gov["user_activity_open"] = False
                try:
                    if gov.get("gemini_activity_open"):
                        await send_activity_end()
                    gov["mode"] = _idle_steer_mode(gov)
                    gov["ready_for_next_utterance"] = True
                    gov["play_steered"] = False
                    gov["asr_finished"] = False
                    _clear_ungoverned_audio_buffer(gov)
                    set_floor("user", reason="silent_close")
                except Exception:
                    _log.exception("silent activity close failed")
                    try:
                        await send_activity_end()
                    except Exception:
                        pass
                finally:
                    gov["commit_scheduled"] = False
                    gov["pending"] = False
                    _reset_vad_turn(gov)

            async def persona_turn_committer() -> None:
                """Persona decides, then Gemini activity_end — never the reverse."""
                try:
                    while not stop.is_set():
                        await asyncio.sleep(0.03)
                        if stop.is_set():
                            return
                        if gov.get("natural_mode"):
                            continue
                        now = time.monotonic()
                        reason = _transcript_commit_reason(gov, voice_cfg, now=now)
                        if not reason:
                            continue
                        last_loud = gov.get("last_loud_mic_at") or now
                        gov["voice_pause_ms"] = int(max(0.0, now - last_loud) * 1000)
                        gov["_last_commit_reason"] = reason
                        _latency_mark(gov, "speech_end", now=last_loud)
                        _latency_mark(gov, "user_commit", now=now)
                        _next_turn_id(gov)
                        gov["commit_scheduled"] = True
                        transcript = _latest_governance_transcript(gov)
                        if transcript and _should_drop_spurious_asr(gov, transcript):
                            _log.info(
                                "commit blocked — echo/spurious ASR: %r",
                                transcript[:80],
                            )
                            gov["commit_scheduled"] = False
                            gov["partial_text"] = ""
                            gov["partial_stable_text"] = ""
                            gov["partial_stable_since"] = 0.0
                            gov["last_user_transcript"] = ""
                            gov["first_partial_at"] = 0.0
                            continue
                        if reason == "end_activity_for_asr":
                            started = gov.get("activity_started_at")
                            if (
                                isinstance(started, (int, float))
                                and now - started < MIN_ACTIVITY_BEFORE_FLUSH_S
                            ):
                                gov["commit_scheduled"] = False
                                continue
                            moved = _relocate_mic_queue_to_recovery(gov, audio_queue)
                            gov["user_activity_open"] = False
                            gov["commit_scheduled"] = False
                            if moved:
                                _log.info(
                                    "relocated %s queued mic chunks before ASR flush",
                                    moved,
                                )
                            drip_n = _promote_recovery_for_flush(gov)
                            gov["mode"] = _idle_steer_mode(gov)
                            gov["play_steered"] = False
                            gov["steer_applied"] = gov.get("natural_mode", False)
                            if not gov.get("natural_mode"):
                                _clear_ungoverned_audio_buffer(gov)
                            if drip_n and gov.get("gemini_activity_open"):
                                gov["flush_asr_after_send"] = True
                                gov["flush_asr_started_at"] = now
                                _log.info(
                                    "defer ASR flush — sending %s recovered chunks first "
                                    "(silence=%sms activity=%.1fs)",
                                    drip_n,
                                    gov["voice_pause_ms"],
                                    now - (started or now),
                                )
                            elif gov.get("gemini_activity_open"):
                                await send_activity_end()
                                _mark_asr_recovery(gov, now=now)
                                _log.info(
                                    "flush ASR — activity_end after speech (silence=%sms activity=%.1fs)",
                                    gov["voice_pause_ms"],
                                    now - (started or now),
                                )
                            else:
                                _mark_asr_recovery(gov, now=now)
                            continue
                        gov["user_activity_open"] = False
                        moved = _relocate_mic_queue_to_recovery(gov, audio_queue)
                        if moved:
                            _log.info(
                                "relocated %s queued mic chunks before commit (%s)",
                                moved,
                                reason,
                            )
                        if reason == "abandon_no_transcript":
                            _log.info(
                                "persona-first abandon — no ASR (activity=%.1fs silence=%.1fs)",
                                now - (gov.get("activity_started_at") or now),
                                now - (gov.get("last_loud_mic_at") or now),
                            )
                            await close_silent_user_activity()
                        elif transcript:
                            flushed = bool(
                                gov.get("activity_end_for_asr")
                                or gov.get("awaiting_asr_recovery")
                            )
                            if not _should_govern_transcript(transcript) and not flushed:
                                _log.info(
                                    "skip governance for weak transcript %r — waiting for speech",
                                    transcript,
                                )
                                gov["commit_scheduled"] = False
                                gov["user_activity_open"] = True
                                gov["partial_text"] = ""
                                gov["partial_stable_text"] = ""
                                gov["partial_stable_since"] = 0.0
                                gov["last_user_transcript"] = ""
                                continue
                            _log.info(
                                "persona-first commit reason=%s silence=%sms transcript=%r",
                                reason,
                                gov["voice_pause_ms"],
                                transcript,
                            )
                            # #region agent log
                            _debug_log(
                                "gemini_live_bridge.py:persona_turn_committer",
                                "VAD commit",
                                {
                                    "reason": reason,
                                    "transcript_len": len(transcript),
                                    "transcript_preview": transcript[:80],
                                },
                                hypothesis_id="H2",
                            )
                            # #endregion
                            outcome = schedule_final_governance(transcript)
                            if outcome == "ignored":
                                if gov.get("natural_mode"):
                                    gov["commit_scheduled"] = False
                                else:
                                    await close_silent_user_activity()
                            elif outcome != "scheduled":
                                gov["commit_scheduled"] = False
                        else:
                            gov["commit_scheduled"] = False
                            gov["user_activity_open"] = True
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _log.exception("persona turn committer failed")

            async def natural_turn_committer() -> None:
                """Natural S2S: silence-based activity_end when ASR final is missing or dropped."""
                try:
                    while not stop.is_set():
                        await asyncio.sleep(0.05)
                        if stop.is_set() or not gov.get("natural_mode"):
                            continue
                        now = time.monotonic()
                        if _natural_abandon_no_transcript_ready(gov, now=now):
                            started = gov.get("activity_started_at") or now
                            _log.info(
                                "natural abandon — no ASR (activity=%.1fs)",
                                now - started,
                            )
                            await close_silent_user_activity()
                            continue
                        if not _natural_silence_commit_ready(gov, voice_cfg, now=now):
                            continue
                        last_loud = gov.get("last_loud_mic_at") or now
                        gov["voice_pause_ms"] = int(max(0.0, now - last_loud) * 1000)
                        gov["_last_commit_reason"] = "natural_silence"
                        _latency_mark(gov, "speech_end", now=last_loud)
                        _latency_mark(gov, "user_commit", now=now)
                        _next_turn_id(gov)
                        gov["natural_endpoint_sent"] = True
                        gov["user_activity_open"] = False
                        transcript = _natural_user_transcript(gov)
                        if not transcript:
                            gov["natural_endpoint_sent"] = False
                            continue
                        _log.info(
                            "natural silence activity_end transcript=%r pause=%sms",
                            (transcript or "")[:80],
                            gov.get("voice_pause_ms"),
                        )
                        # #region agent log
                        _debug_log(
                            "gemini_live_bridge.py:natural_turn_committer",
                            "natural silence endpoint",
                            {
                                "transcript_preview": (transcript or "")[:80],
                                "pause_ms": gov.get("voice_pause_ms"),
                            },
                            hypothesis_id="H3",
                        )
                        # #endregion
                        if gov.get("gemini_activity_open"):
                            try:
                                await send_activity_end()
                                gov["last_gemini_send"] = time.monotonic()
                            except Exception as exc:
                                _log.warning(
                                    "natural activity_end failed: %s — will resume",
                                    exc,
                                )
                                if _is_gemini_goaway_error(exc) or _gemini_ws_close_code(exc) == "1007":
                                    await resume_gemini("natural_endpoint_1007")
                        if transcript and transcript.strip():
                            gov["asr_finished"] = True
                            asyncio.create_task(
                                apply_governance(
                                    transcript.strip(),
                                    partial=False,
                                    persist=True,
                                )
                            )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _log.exception("natural turn committer failed")

            async def recover_stuck_voice_pipeline(reason: str) -> None:
                """Clear ASR/governance deadlock and optionally refresh Gemini Live."""
                now = time.monotonic()
                last = float(gov.get("last_pipeline_recovery_at") or 0.0)
                if last > 0 and (now - last) < PIPELINE_RECOVERY_COOLDOWN_S:
                    return
                gov["last_pipeline_recovery_at"] = now
                _log.warning("voice pipeline recovery (%s)", reason)
                for key in ("partial_task", "final_task", "late_asr_task"):
                    task = gov.get(key)
                    if task is not None and not task.done():
                        task.cancel()
                    gov[key] = None
                _clear_asr_recovery(gov)
                gov["flush_asr_after_send"] = False
                gov["flush_asr_started_at"] = 0.0
                gov["recovery_generation_complete"] = False
                gov["recovery_mic_pending"] = []
                gov["recovery_mic_buffer"] = []
                gov["pending"] = False
                gov["commit_scheduled"] = False
                gov["awaiting_turn_complete"] = False
                gov["model_generating"] = False
                gov["final_scheduled_for"] = ""
                gov["accept_mic"] = True
                gov["ready_for_next_utterance"] = True
                gov["mic_pacing_reset"] = True
                _reset_vad_turn(gov)
                # Echo often triggers speech_without_activity on HP — never reconnect mid-reply.
                if reason == "speech_without_activity":
                    if gov.get("gemini_activity_open"):
                        try:
                            await send_activity_end()
                        except Exception:
                            pass
                    return
                enqueue_browser(
                    {
                        "type": "notice",
                        "message": "Voice dipulihkan — silakan bicara lagi.",
                    }
                )
                if not await resume_gemini(f"recover_{reason}"):
                    enqueue_browser(
                        {
                            "type": "notice",
                            "message": "Voice masih lambat — coba bicara lagi atau mulai panggilan baru.",
                        }
                    )

            async def asr_stuck_watchdog() -> None:
                try:
                    while not stop.is_set():
                        await asyncio.sleep(2.0)
                        if stop.is_set():
                            return
                        if _recover_natural_turn_stuck(gov):
                            enqueue_browser(
                                {
                                    "type": "notice",
                                    "message": "Voice siap lagi — silakan lanjut bicara.",
                                }
                            )
                        reason = _voice_pipeline_stuck(gov)
                        if reason:
                            await recover_stuck_voice_pipeline(reason)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _log.exception("asr stuck watchdog failed")

            async def call_session_watchdog() -> None:
                """Retell max duration + end call on extended user silence."""
                try:
                    while not stop.is_set():
                        await asyncio.sleep(5.0)
                        if stop.is_set():
                            return
                        now = time.monotonic()
                        started = gov.get("session_started_at")
                        if (
                            call_cfg.max_call_duration_ms > 0
                            and isinstance(started, (int, float))
                            and int((now - started) * 1000) >= call_cfg.max_call_duration_ms
                        ):
                            await end_call(
                                "max_duration",
                                "Sesi voice sudah mencapai batas durasi.",
                            )
                            return
                        connected = gov.get("gemini_connected_at")
                        go_away_at = gov.get("go_away_at") or 0
                        need_goaway = isinstance(go_away_at, (int, float)) and go_away_at > 0
                        need_ttl = (
                            isinstance(connected, (int, float))
                            and connected > 0
                            and (now - connected) >= GEMINI_LIVE_REFRESH_S
                        )
                        if (need_ttl or need_goaway) and _live_session_idle(gov):
                            reason = "go_away_idle" if need_goaway else "ttl"
                            _log.info(
                                "Gemini Live refresh (%s) after %.0fs",
                                reason,
                                now - float(connected or 0),
                            )
                            if not await resume_gemini(reason):
                                _log.warning(
                                    "Gemini Live refresh delayed (%s); will retry next tick",
                                    reason,
                                )
                            continue
                        if call_cfg.end_call_on_silence_ms <= 0:
                            continue
                        if (
                            gov.get("user_activity_open")
                            or gov.get("gemini_activity_open")
                            or _answer_in_flight(gov)
                            or gov.get("pending")
                        ):
                            continue
                        last_user = gov.get("last_user_activity_at")
                        if not isinstance(last_user, (int, float)):
                            continue
                        silent_ms = int((now - last_user) * 1000)
                        if silent_ms >= call_cfg.end_call_on_silence_ms:
                            await end_call(
                                "silence_timeout",
                                "Sesi diakhiri karena tidak ada suara dari user.",
                            )
                            return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _log.exception("call session watchdog failed")

            async def natural_agent_audio_watchdog() -> None:
                """Natural S2S: Gemini often skips turn_complete — yield mic after agent audio."""
                try:
                    while not stop.is_set():
                        await asyncio.sleep(0.5)
                        if stop.is_set() or not gov.get("natural_mode"):
                            continue
                        last_fwd = gov.get("last_forward_at")
                        if not isinstance(last_fwd, (int, float)) or last_fwd <= 0:
                            continue
                        now = time.monotonic()
                        if now - last_fwd < 1.6:
                            continue
                        last_tc = float(gov.get("last_turn_complete_at") or 0.0)
                        if last_tc >= last_fwd:
                            continue
                        if gov.get("user_activity_open") or gov.get("gemini_activity_open"):
                            continue
                        _log.info(
                            "natural S2S force yield — agent audio done, no turn_complete (%.1fs)",
                            now - last_fwd,
                        )
                        gov["model_generating"] = False
                        gov["awaiting_turn_complete"] = False
                        gov["accept_mic"] = True
                        gov["ready_for_next_utterance"] = True
                        gov["commit_scheduled"] = False
                        gov["last_turn_complete_at"] = now
                        await _on_safe_turn_boundary(
                            gov,
                            session,
                            reason="natural_audio_done",
                            send_lock=session_send_lock,
                            yield_turn=yield_turn_to_user,
                            persist=persist_spoken_reply,
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _log.exception("natural agent audio watchdog failed")

            browser_task = asyncio.create_task(browser_sender())
            forward_in = asyncio.create_task(client_to_gemini())
            forward_out = asyncio.create_task(gemini_to_client())
            audio_out = asyncio.create_task(gemini_audio_sender())
            keepalive = asyncio.create_task(gemini_keepalive())
            greeting = asyncio.create_task(send_opening_greeting())
            greeting_fallback_task = asyncio.create_task(greeting_mic_fallback())
            gov["greeting_fallback_task"] = greeting_fallback_task
            committer = asyncio.create_task(persona_turn_committer())
            natural_committer = asyncio.create_task(natural_turn_committer())
            asr_watchdog = asyncio.create_task(asr_stuck_watchdog())
            natural_audio_watchdog = asyncio.create_task(natural_agent_audio_watchdog())
            watchdog = asyncio.create_task(call_session_watchdog())
            _log.info("live bridge tasks started (persona-first turn commit)")
            _latency_mark(gov, "session_active")
            emit_latency("connect", turn_id=0)
            await ws.send_json(
                {
                    "type": "status",
                    "state": "active",
                    "session_id": session_ref["id"],
                    "voice_config": voice_cfg.to_client_dict(),
                    "call_config": call_cfg.to_client_dict(),
                    "post_call_config": post_call_cfg.to_client_dict(),
                    "security_config": security_cfg.to_client_dict(),
                    "webhook_config": webhook_cfg.to_client_dict(),
                    "live_mode": live_mode.to_client_dict(),
                }
            )
            if not gov.get("webhook_call_started_sent"):
                schedule_webhook("call_started", build_live_call(status="ongoing"))
                gov["webhook_call_started_sent"] = True
            await stop.wait()
            try:
                audio_queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
            try:
                browser_out.put_nowait(None)
            except asyncio.QueueFull:
                pass
            greeting.cancel()
            greeting_fallback_task.cancel()
            committer.cancel()
            natural_committer.cancel()
            asr_watchdog.cancel()
            natural_audio_watchdog.cancel()
            watchdog.cancel()
            keepalive.cancel()
            forward_in.cancel()
            forward_out.cancel()
            audio_out.cancel()
            browser_task.cancel()
            for task_key in ("partial_task", "final_task", "late_asr_task"):
                task = gov.get(task_key)
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(
                forward_in,
                forward_out,
                audio_out,
                keepalive,
                browser_task,
                committer,
                natural_committer,
                return_exceptions=True,
            )
    except Exception as exc:
        err_msg = str(exc).strip() or repr(exc)
        _log.exception("Gemini Live session failed")
        try:
            await ws.send_json({"type": "error", "message": f"Gemini Live: {err_msg}"})
        except Exception:
            pass
    finally:
        _last_transcript.pop(session_ref["id"], None)
        if webhook_cfg.should_emit("call_ended") and not gov.get("webhook_call_ended_sent"):
            end_reason = str(gov.get("call_end_reason") or "session_end")
            try:
                deliver_webhook_event(
                    webhook_cfg,
                    event="call_ended",
                    call=build_call_object(
                        session_id=session_ref["id"],
                        agent_id=profile.preset_id,
                        call_status="ended",
                        duration_ms=(
                            int((time.monotonic() - gov["session_started_at"]) * 1000)
                            if isinstance(gov.get("session_started_at"), (int, float))
                            else 0
                        ),
                        end_reason=end_reason,
                        voice_name=voice_cfg.voice_name,
                        language_code=voice_cfg.language_code,
                    ),
                    dynamic_variables=dyn_vars,
                )
            except Exception:
                _log.exception("webhook call_ended on disconnect failed")
        if not gov.get("post_call_scheduled") and post_call_cfg.enabled:
            gov["post_call_scheduled"] = True
            started = gov.get("session_started_at")
            duration_ms = 0
            if isinstance(started, (int, float)):
                duration_ms = int((time.monotonic() - started) * 1000)
            end_reason = str(gov.get("call_end_reason") or "session_end")

            async def _post_call_on_disconnect() -> None:
                try:
                    result = await asyncio.to_thread(
                        extract_post_call_data,
                        runtime,
                        session_ref["id"],
                        config=post_call_cfg,
                        end_reason=end_reason,
                        duration_ms=duration_ms,
                        api_key=api_key,
                        security_cfg=security_cfg,
                    )
                    if result:
                        data = result.get("data") or {}
                        try:
                            await ws.send_json(
                                {
                                    "type": "post_call_data",
                                    "session_id": session_ref["id"],
                                    "data": data,
                                    "model": result.get("model"),
                                }
                            )
                        except Exception:
                            pass
                        if webhook_cfg.should_emit("call_analyzed"):
                            await asyncio.to_thread(
                                deliver_webhook_event,
                                webhook_cfg,
                                event="call_analyzed",
                                call=build_call_object(
                                    session_id=session_ref["id"],
                                    agent_id=profile.preset_id,
                                    call_status="ended",
                                    duration_ms=duration_ms,
                                    end_reason=end_reason,
                                    voice_name=voice_cfg.voice_name,
                                    language_code=voice_cfg.language_code,
                                    call_analysis=result.get("data") or {},
                                ),
                                dynamic_variables=dyn_vars,
                            )
                except Exception:
                    _log.exception("post-call extraction on disconnect failed")

            try:
                asyncio.create_task(_post_call_on_disconnect())
            except RuntimeError:
                pass
        try:
            await ws.send_json({"type": "status", "state": "ended"})
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass
