# Persona AI — Arsitektur Server

## Dua mode terpisah

| Platform | Server berjalan di |
|----------|-------------------|
| **Web (browser PC)** | PC — jalankan `start_server.bat` → `http://127.0.0.1:8765` |
| **HP (Android app)** | HP — Chaquopy + Python embedded @ `127.0.0.1:8765` |

Tidak ada fallback HP → PC. App Android **hanya** pakai backend lokal di perangkat.

## Arsitektur HP

```
[HP Android App]
  ├── ByokStore (EncryptedSharedPreferences) → GEMINI_API_KEY
  ├── PersonaServerService → Python embedded (Chaquopy)
  │     └── persona_ai.web.server @ 127.0.0.1:8765
  └── WebView → http://127.0.0.1:8765/?app=1
```

## Build APK

```bat
cd android
gradlew.bat assembleDebug
```

Backend Python + deps di-bundle otomatis (`embedPython=true` default).

Jika build gagal di pydantic-core (Windows), coba WSL/Linux atau tunggu wheel Chaquopy.

Matikan bundling deps (hanya untuk debug):

```bat
gradlew.bat assembleDebug -PembedPython=false
```

## Web dev (PC)

```bat
start_server.bat
```

Buka browser: `http://127.0.0.1:8765`

## Play Store / BYOK

- Tidak perlu server cloud milik developer
- Biaya API ditanggung user (Google AI Studio)
- Session SQLite disimpan lokal di HP (`PERSONA_SESSION_DB`)
