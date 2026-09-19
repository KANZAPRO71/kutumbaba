# Play Console — Data safety (draft mapping)

Use this when filling **Data safety** for Papua AI. Adjust if implementation changes.

## App collects / processes

| Data type | Collected | Shared | Purpose | Optional |
|-----------|-----------|--------|---------|----------|
| Audio (microphone) | Yes | Yes (Google Gemini via user API key) | Voice conversation | No (core feature) |
| Messages / conversation content | Yes | Yes (Gemini) | AI companion | No |
| User-provided API key | Yes | No (stored on device) | Authentication to Gemini | No |
| App interactions (memories, prefs) | Yes | No | Personalization, local RAG | Partial (RAG toggle) |
| Crash logs | Only if you add Firebase/Crashlytics later | — | — | — |

## Storage

- **On device:** session DB, user memory DB, encrypted/plain prefs for API key, WebView localStorage copy of key.
- **Developer servers:** none for conversation content (local-first backend on device).

## Third party

- **Google Gemini API** — user BYOK; data processing under Google's terms.

## Security practices (claim only what is true)

- Data encrypted in transit (HTTPS to Gemini).
- API key excluded from Android full backup rules (`persona_byok_*` prefs).
- Users can delete local memory in Settings.

## Privacy policy URL (for Console)

- GitHub Pages: `https://kanzapro71.github.io/kutumbaba/privacy.html`
- Or host the same file from your Play listing domain.

## AI disclosure (store listing)

- State that responses are AI-generated (Google Gemini).
- User must supply their own API key.
- Not a substitute for professional advice.
