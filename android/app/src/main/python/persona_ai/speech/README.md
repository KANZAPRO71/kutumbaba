# Speech Engine

STT/TTS abstraction — optional for text-only channels.

## Tanggung jawab

- `transcribe(audio) → text + confidence`
- `synthesize(text, voice_profile, prosody) → audio`
- Prosody dari `BehaviorDecision.timing` & `interjection`

## Dependency

- **Depends on:** `core`
- **Used by:** `conversation`, `session` (ingress)
