# Persona — Teman Ngobrol (Web UI)

Voice-first companion — bukan chatbot asisten. UI dalam Bahasa Indonesia.

| Mode | Transport | Backend |
|------|-----------|---------|
| Suara (utama) | `WS /api/live/ws` | Mic PCM → Gemini Live → speaker PCM |
| Teks (opsional) | `POST /api/chat` | PersonaRuntime → Gemini |

Naturalness: PersonaRuntime (BDV + VoiceDirective) memutuskan setiap giliran **sebelum** Gemini Live bicara.

## Run

```powershell
pip install -e ".[web,gemini]"
persona-chat
```

Buka: http://127.0.0.1:8765

Atau: `start_server.bat` dari root project.

## Fitur UI

- Tombol **Ngobrol** (voice-first)
- Onboarding: teman ngobrol, bukan layanan pelanggan
- Banner lanjut obrolan kemarin
- Kartu ringkasan setelah ngobrol
- Chat teks tersembunyi — klik **Tulis pesan…** jika perlu

## Env

| Variable | Default |
|----------|---------|
| `GEMINI_API_KEY` | required |
| `PERSONA_PRESET` | `default_companion` |

Hard refresh setelah update static: `Ctrl+Shift+R` (atau buka ulang tab).
