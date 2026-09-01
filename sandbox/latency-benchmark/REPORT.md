# E2E Latency Benchmark — Persona

**Measured:** 2026-08-27T14:48:02Z

## What we can measure without a browser

| Slice | Persona | Reference budget |
|-------|---------|------------------|
| WS connect | connect **734.0 ms** | network 30–80 ms |
| BDV governance (local) | **0.2 ms** | < 80 ms pre-LLM |
| Governance / orchestration | governance **125.0 ms** | turn-taking 150–300 ms |
| Commit → first steered audio | commit_to_audio **1110.0 ms** | **~600 ms** E2E target |

## Persona — local probes

- `GET /api/health`: {"name": "persona_health", "n": 5, "min_ms": 3.4, "median_ms": 15.5, "mean_ms": 24.3, "p90_ms": 59.5, "max_ms": 59.5}
- `PersonaRuntime.process_turn` (voice channel, no Gemini): {"name": "persona_bdv", "n": 5, "min_ms": 0.1, "median_ms": 0.2, "mean_ms": 0.8, "p90_ms": 3.1, "max_ms": 3.1}

### Persona Live log samples

- Parsed `turn latency` lines: **34**
- Connect: {"name": "persona_connect", "n": 1, "min_ms": 734.0, "median_ms": 734.0, "mean_ms": 734.0, "p90_ms": 734.0, "max_ms": 734.0}
- Greeting → audio: {"name": "persona_greeting_to_audio", "n": 0}
- Commit → audio: {"name": "persona_commit_to_audio", "n": 1, "min_ms": 1110.0, "median_ms": 1110.0, "mean_ms": 1110.0, "p90_ms": 1110.0, "max_ms": 1110.0}
- Governance only: {"name": "persona_governance", "n": 1, "min_ms": 125.0, "median_ms": 125.0, "mean_ms": 125.0, "p90_ms": 125.0, "max_ms": 125.0}
- Steer → audio: {"name": "persona_steer_to_audio", "n": 1, "min_ms": 985.0, "median_ms": 985.0, "mean_ms": 985.0, "p90_ms": 985.0, "max_ms": 985.0}

## Interpretation

### Persona overhead (expected)
- **Persona-first pipeline**: VAD wait (~500 ms silence floor) + ASR stability (200–600 ms) + BDV + ENGINE steer + second Gemini audio pass.
- Local BDV slice ~**0.2 ms** — small vs total E2E.
- Main cost is **governance + steered re-generation**, not BDV CPU.

### Rough E2E model (Persona voice turn)

```
vad_wait        ~500–850 ms   (silence + STT grace + partial stability)
governance_ms   ~50–200 ms    (BDV + steer inject)
steer_to_audio  ~300–800 ms   (Gemini generates steered PCM)
─────────────────────────────
commit_to_audio ~900–1800 ms  (typical; measure after live Call)
```

## Next measurement

1. Restart server (`persona-chat.exe`)
2. Hard refresh → one voice Call → ask 3 questions
3. Re-run: `python sandbox/latency-benchmark/measure_e2e.py --log terminals/<id>.txt`
