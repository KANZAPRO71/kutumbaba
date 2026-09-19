# Papua AI — Unified Live Architecture (four pillars)

Single **async session** per voice call: `handle_live_websocket` in
`persona_ai/web/gemini_live_bridge.py`. Integration facade and blueprint mapping:
`persona_ai/bridge/gemini_live_bridge.py` (`PapuaAILiveEngine`).

**Hard rule:** PCM capture, VAD, turn detection, and mic pacing are unchanged.

```
┌──────────────── WebView (live.js) ────────────────┐
│ Mic PCM → WS │ Agent audio ← jitter queue + AC   │
│ link_state UI (suspended / live / disconnected) │
└───────────────────────┬─────────────────────────┘
                        │ browser WebSocket
┌───────────────────────▼─────────────────────────┐
│ handle_live_websocket  (Unified Async Engine)      │
│  ├─ gemini_to_client / browser_sender queues       │
│  ├─ P1 _spawn_live_tool_call (NON_BLOCKING tools)  │
│  ├─ P2 situational_context_heartbeat               │
│  ├─ P3 apply_mid_call_experience_mode              │
│  └─ P4 resume_gemini + live_resilience link_state  │
└───────────────────────┬─────────────────────────┘
                        │ google.genai Live SDK
                        ▼
                   Gemini Live (BYOK)
```

## Pillar 1 — Async non-blocking tools

- Registry: `persona_ai/plugins/registry.py` (`non_blocking=True`)
- Live dispatch: `persona_ai/plugins/live_dispatch.py`
- Bridge: `_spawn_live_tool_call` → `asyncio.create_task` + `to_thread` → `send_tool_response`
- Doc: `persona_ai/plugins/LIVE_ASYNC_TOOLS.md`

## Pillar 2 — Real-time context injection

- Core: `live_context_injection.py` — `[SITUATIONAL_CONTEXT_UPDATE: …]`, `turn_complete=False`
- Facade: `persona_ai/bridge/sensor_monitor.py` (`fetch_sensor_snapshot`, `send_dynamic_context`)
- Heartbeat: `situational_context_heartbeat` (embedded app, ~30s / signature change)
- Android: `DeviceContextBridge.getTelemetryJson`
- Disable: `PERSONA_LIVE_CONTEXT_INJECT=0`

## Pillar 3 — Dynamic experience mode meta-prompt

- Manifest: `persona_ai/conversation/experience_modes.py`
- WebView: Settings → `setConversationMode` → WS `conversation_mode`
- Bridge: `apply_mid_call_experience_mode` + `live_mode_meta_injection.py` (`[META_SYSTEM_OVERRIDE: …]`)
- Idle gate: `live_pipeline_state.live_pipeline_idle` — no inject while mic/ASR/reply busy
- Disable meta inject (fallback realtime steer): `PERSONA_LIVE_META_INJECT=0`

## Pillar 4 — Network resiliency & playback jitter

| Layer | Mechanism |
|-------|-----------|
| Gemini transport | `resume_gemini`, session resumption handles |
| Link state | `live_resilience.py` → `link_state` events to WebView |
| Browser WS | Soft reconnect in `live.js` (3 attempts) |
| Agent playback jitter | `_jitterQueue` in `live.js` (`JITTER_MIN_CHUNKS=3`, suspended lookahead 180ms) |

### Link state machine

```
idle → connected (call active)
connected ⇄ resuming / suspended (Gemini heal)
suspended → disconnected (fatal resume / rate limit / user stop)
```

UI: `app.js` `onLinkState` — brief drops show “Menyambung ulang…” without auto-hangup.

## Blueprint vs repository paths

| Blueprint path | Actual |
|----------------|--------|
| `src/persona_ai/bridge/gemini_live_bridge.py` | Facade + `PapuaAILiveEngine` map |
| `src/persona_ai/config/experience_modes.py` | `persona_ai/conversation/experience_modes.py` |
| `src/persona_ai/bridge/sensor_monitor.py` | Facade over `live_context_injection.py` |
| Raw `websockets` + AudioTrack jitter | **Not used** — SDK + WebView playback |

## Android WebView bridge (experience mode)

| Layer | Symbol |
|-------|--------|
| JS | `setSelectedConversationMode` → in-call: WS `conversation_mode`; idle: `PersonaAndroid.onModeChanged` |
| Kotlin | `PersonaAndroidBridge.onModeChanged`, alias `window.Android` |
| Python | `persona_ai.plugins.webview_bridge.handle_ui_mode_change` |
| Live fallback | `live_session_hub.request_mode_change_from_ui` (deduped with WS via `note_mode_applied_via_websocket`) |

No separate `PapuaAILiveEngine` instance in Kotlin — the live session is the embedded server + `handle_live_websocket`.

## Build / deploy

Gradle copies `src/persona_ai` → `android/app/src/main/python/persona_ai` before Chaquopy build.
After changing bridge or live JS, bump cache query in `static/index.html` and `assembleDebug`.

## Suggested field tests

1. Mode switch mid-call (P3) — no WS reconnect, toast + persona shift.
2. Airplane mode &lt; 3s (P4) — suspended UI, audio continues from jitter buffer if chunks queued.
3. Tool call during speech (P1) — agent keeps talking while plugin runs.
4. Walk with GPS change (P2) — context inject in logs, no user turn committed.
