# Papua AI — Arsitektur sistem (ringkas)

Dokumen indeks untuk developer. Detail per area ada di file terlink.

## Stack

| Lapisan | Teknologi | Lokasi utama |
|---------|-----------|--------------|
| UI | WebView premium (HTML/CSS/JS) | `src/persona_ai/web/static/` |
| Native shell | Kotlin + WebView bridge | `android/app/src/main/java/com/persona/ai/` |
| Backend on-device | Python 3.13 (Chaquopy) + FastAPI | `src/persona_ai/web/server.py` |
| Voice realtime | Gemini Live BYOK (`google-genai`) | `src/persona_ai/web/gemini_live_bridge.py` |
| Persona / BDV | PersonaRuntime, ConversationController | `src/persona_ai/runtime.py`, `web/conversation_controller.py` |

**Invariant:** pipa tangkap mic native (PCM), VAD, turn detection, dan pacing **tidak** diubah oleh fitur mutakhir — hanya layer transport & governance di atasnya.

## Alur satu panggilan suara

```
User tap "Buka Suara"
  → WebView live.js: mic → browser WebSocket
  → gemini_live_bridge.handle_live_websocket
  → Persona governance (BDV) → Gemini Live audio/text
  → Agent PCM → live.js jitter queue → AudioContext playback
```

## Empat pilar live (non-memori)

| # | Nama | Dokumen / modul |
|---|------|-----------------|
| 1 | Async non-blocking tools | [LIVE_ASYNC_TOOLS.md](../src/persona_ai/plugins/LIVE_ASYNC_TOOLS.md) |
| 2 | Context injection (GPS/baterai) | `live_context_injection.py`, `bridge/sensor_monitor.py` |
| 3 | Mid-call experience mode | `live_mode_meta_injection.py`, WS `conversation_mode` |
| 4 | Resiliency + jitter | `live_resilience.py`, `live.js` `_jitterQueue`, `resume_gemini` |

Peta lengkap: [LIVE_ARCHITECTURE.md](../src/persona_ai/web/LIVE_ARCHITECTURE.md).

Facade integrasi blueprint: `persona_ai/bridge/gemini_live_bridge.py` (`PapuaAILiveEngine` = peta simbol, bukan WS kedua).

## Bridge Android ↔ WebView ↔ Python

```
Experience mode (idle)     PersonaAndroid.onModeChanged → webview_bridge.py
Experience mode (in-call)  live.js → WS conversation_mode → apply_mid_call_experience_mode
Lifecycle                  MainActivity onPause/onDestroy → PersonaWaveform.pause, webview_bridge.on_app_lifecycle
Telemetry                  DeviceContextBridge → live_context_injection heartbeat
BYOK                       PersonaAndroid.setApiKey → ByokStore → PersonaServerService
```

Performa & APK: [ANDROID_PERFORMANCE.md](ANDROID_PERFORMANCE.md).  
BYOK & keystore: [BYOK_ANDROID.md](BYOK_ANDROID.md).

## Build & sync Python

Gradle task `syncPersonaPython` menyalin `src/persona_ai` → `android/app/src/main/python/persona_ai` sebelum compile.

```bat
cd android
gradlew.bat assembleDebug
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

ABI default: `arm64-v8a`. `-PpersonaAbi=arm32` untuk APK lebih lebar perangkat.

## UI premium (WebView)

- Glass + gold/emerald, orb cenderawasih, canvas visualizer (`waveform-viz.js`)
- Strip mode in-call → `setSelectedConversationMode` (Pilar 3)
- Cache bust: query `?v=` di `index.html` untuk `styles.css`, `app.js`, `live.js`

## Pengujian lapangan (prioritas)

1. Ganti mode mid-call — persona bergeser, tidak putus WS browser.
2. Jaringan flicker — UI "Menyambung ulang…", audio tidak patah parah.
3. Plugin non-blocking saat agent bicara — suara agent tidak freeze.
4. Background app — visualizer pause; server tetap hidup selama panggilan.

## Yang sengaja di luar scope (beta saat ini)

- Memori jangka panjang / Mem0-style expansion
- Alarm plugin, haptic
- Agent TTS via Android AudioTrack (playback agent = WebView)
