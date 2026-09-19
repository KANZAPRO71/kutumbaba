# Gemini Live — Async Non-Blocking Tools

Papua AI keeps **PCM / VAD / turn detection unchanged**. Tool calling lives entirely in the
WebSocket event layer (`gemini_live_bridge.py` + `plugins/`).

## Layers

```
Gemini Live (tool_call + audio in parallel when NON_BLOCKING)
    ↓ LiveServerMessage.tool_call
gemini_to_client receive loop  →  _spawn_live_tool_call (create_task, no await)
    ↓ asyncio.to_thread
plugins.registry.invoke_tool  →  device / web_search handlers
    ↓ send_tool_response (session_send_lock)
Gemini continues speech with function result
```

## Registration

- `register_tool(..., non_blocking=True)` — default for I/O plugins.
- `live_function_declarations()` adds `"behavior": "NON_BLOCKING"` for the Live handshake.
- `live_session_tools(embedded_app, async_web_search)` builds `types.Tool(function_declarations=...)`
  inside `_live_connect_config` (google-genai SDK, not raw JSON setup).

## Runtime rules

1. **Never `await` plugin work inside `gemini_to_client`** — only `_spawn_live_tool_call`.
2. **Plugin handlers stay sync**; blocking I/O runs in `asyncio.to_thread`.
3. **`session_send_lock`** serializes `send_tool_response` with mic sends / steer.
4. **Filler speech** is Gemini’s job when `Behavior.NON_BLOCKING` is set on the declaration;
   tool descriptions remind the model to keep talking (logat Papuan).

## Current tools

| Tool | NON_BLOCKING | Notes |
|------|----------------|-------|
| `search_live_web` | yes | Google Search grounding via sync fetch in thread |
| `get_location_snapshot` | yes | Android `DeviceContextBridge` |
| `get_device_status` | yes | Battery / network |

## Situational back-channel (Android embedded)

Separate from tool calling — Python pushes telemetry **to** Gemini while audio continues:

- Module: `persona_ai/web/live_context_injection.py`
- API: `session.send_client_content(turns=[...], turn_complete=False)`
- Payload: `[SITUATIONAL_CONTEXT_UPDATE: …]` (GPS bucket, movement, battery, network)
- Source: `DeviceContextBridge.getTelemetryJson()` via Chaquopy
- Heartbeat: `situational_context_heartbeat` task in live bridge (30s / on signature change)
- Disable: `PERSONA_LIVE_CONTEXT_INJECT=0`

Does **not** replace tools — tools answer explicit user requests; back-channel keeps the model aware between turns.

## Dynamic experience mode (mid-call)

No reconnect — WebView `setConversationMode` → WS `conversation_mode` → `apply_mid_call_experience_mode`:

- Gov + BDV: `experience_mode_switch.prepare_live_experience_mode_switch` (uses `experience_modes.py`, not a duplicate manifest)
- Prompt: `mid_session_experience_mode_steer` wrapped as `[META_SYSTEM_OVERRIDE: …]` + `send_client_content(turn_complete=False)`
- UI: `app.js` already calls `liveCall.setConversationMode` when settings mode changes during call

## Not used

- Raw `websockets` + manual JSON envelopes (SDK handles wire format).
