# Papua AI — Android performance & release notes

## Lifecycle (WebView + Chaquopy)

| Event | Behavior |
|-------|----------|
| `onPause` | `WebView.onPause()`, `pauseTimers()`, JS `__personaPauseUi` → `PersonaWaveform.pause()` |
| `onResume` | `resumeTimers()`, JS `__personaResumeUi` |
| `onDestroy` (finishing) | Remove `PersonaAndroid` / `Android` JS interfaces, load `about:blank`, `destroy()`, Python `webview_bridge.on_app_lifecycle("destroy")` |

Embedded Python **server** (`PersonaServerService`) stays up in background so an active voice call can continue; only WebView rendering is paused.

## APK size (Chaquopy / NDK)

Default **`arm64-v8a` only** (smaller APK on modern phones).

```bash
# 32+64-bit ARM (wider device support, larger APK)
gradlew assembleDebug -PpersonaAbi=arm32

# Emulators / all ABIs (largest)
gradlew assembleDebug -PpersonaAbi=all
```

Python deps come from `android/requirements-chaquopy.txt` — do not add unused packages (e.g. raw `websockets` is not required; Gemini uses `google-genai`).

## Network security

- Manifest: `INTERNET`, `ACCESS_NETWORK_STATE`, `hardwareAccelerated=true`
- `usesCleartextTraffic=false` globally; **localhost / 127.0.0.1** cleartext allowed via `network_security_config.xml` for the embedded server
- Gemini Live uses HTTPS/WSS from Python — not affected by cleartext rules

## Build & install (field device)

```bash
cd android
gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Architecture map

See `src/persona_ai/web/LIVE_ARCHITECTURE.md` (four pillars + WebView bridge).
