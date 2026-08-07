# Jarvis — your voice-first AI that remembers

Jarvis is a **voice-first personal AI assistant** you actually talk to. Hold a real
conversation — Jarvis listens, answers out loud, and **remembers what matters about
you across every chat**. Most AI apps forget you the moment you close them. Jarvis
doesn't: tell it about the people, projects, and details in your life, and it keeps
them, getting smarter and more personal every time you talk.

## What Jarvis can do

- **Talk naturally** — a hands-free voice assistant for questions, ideas, and thinking out loud (with a text fallback when you'd rather type).
- **Remember anything** — names, dates, preferences, context. Jarvis extracts durable facts and recalls them later.
- **Never drop the ball** — say "remind me to call Sarah tomorrow" and Jarvis tracks the follow-up.
- **Answer with sources** — live Google Search grounding through Gemini for weather, news, and facts.
- **Morning brief** — a one-tap summary of what you can't afford to forget today.

## Why Jarvis

- **Voice first** — designed for speaking, not typing.
- **It remembers you** — builds real context over time.
- **Private by design** — your conversations, memories, and reminders stay in your
  browser (`localStorage`). They're never sold or mined. Only your messages go to
  Google, via your own key.
- **Free** — bring your own Google Gemini API key. No subscription, no lock-in.

## How to start

Jarvis runs on your own Google Gemini API key (free to create at
[Google AI Studio](https://aistudio.google.com/app/apikey)).

```bash
npm install       # no runtime dependencies — this just sets up the project
npm start         # serves the app at http://localhost:3000
```

Then open http://localhost:3000, paste your Gemini key once during setup, and start
talking. An optional email field just saves your address for product updates — no
account is required to use the app.

### Demo mode (no key needed)

Leave the API key blank and Jarvis runs in **offline demo mode**. The full
conversation loop still works: it extracts and remembers facts, tracks reminders,
and generates your morning brief entirely on-device. Live web answers with sources
require a Gemini key.

## Architecture

Jarvis is a fully client-side app; the Node server only serves static files.

| Path | Responsibility |
| --- | --- |
| `server.js` | Zero-dependency static file server (+ `/health`). |
| `public/index.html`, `public/styles.css` | App shell and UI. |
| `public/js/app.js` | Controller: wires store, providers, voice, and UI. |
| `public/js/store.js` | Persistent memory/reminders/conversation in `localStorage`. |
| `public/js/providers.js` | `GeminiProvider` (live, with Google Search sources) + `DemoProvider` (offline). |
| `public/js/voice.js` | Speech-to-text and text-to-speech wrappers. |
| `public/js/core/*` | Pure logic: fact extraction, due-date parsing, morning brief, demo brain. |

The `core/` modules are pure and framework-free, which is why the memory, reminder,
and brief features are covered by fast unit tests.

## Tests

```bash
npm test          # runs node --test over tests/
```

## Privacy

Everything Jarvis remembers lives in your browser. There is no Jarvis backend that
stores your data. Your Gemini API key is kept in `localStorage` and used only to call
Google's Generative Language API directly from your browser.
