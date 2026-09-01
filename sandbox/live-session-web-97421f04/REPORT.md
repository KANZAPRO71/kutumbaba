# Live session debug — web-97421f04

Source: `terminals/412739.txt` (persona-chat, ignore-interrupt restart).
Artifacts: `timeline.csv`, `incidents.tsv`, `rms-stats.txt`, `transcript.txt`, `analysis.json`.

## What happened

Mic PCM kept flowing (3200-byte / 100 ms frames). Gemini answered every turn.
Persona then **threw that answer away**, ran BDV on a **partial** transcript, injected ENGINE steer, and waited for a **second** audio turn.

That loop is the choppiness: suppress → steer → `interrupted` → hold gate → new PCM.

## Incident counts

| Kind | Count |
|---|---|
| `user transcript final` | **0** |
| `user transcript partial` | 16 |
| FINAL_TRANSCRIPT_MISSING | 14 (13× `suppressed_audio`, 1× `turn_complete`) |
| SUPPRESS (sampled) | 16 (running total reached **130** chunks) |
| GOVERNANCE | 14 |
| GEMINI_INTERRUPTED | 13 |
| AUDIOGATE_HOLD | 14 (3× `seen=False`: Halo, nomor satu, Berapa lagi?) |

Canonical per-turn sequence (13/14 turns):

```
partial ASR → suppressed ungoverned audio → fallback governance
→ steer=engine play_steered=True → gemini interrupted (kept)
→ gate hold awaiting steered audio → forward mode=engine
```

## Transcript / BDV

No final ASR line was ever logged. Every governed turn used the latest partial.

| # | Partial | BDV | Problem |
|---|---|---|---|
| 1 | Halo. | RESPOND | OK (greeting) |
| 2 | semuanya | ACK_ONLY | fragment |
| 3 | Ada 100 pertanyaan. | ACK_ONLY | intent, no `?` |
| 4 | nomor satu | ACK_ONLY | fragment |
| 5 | Namamu siapa? | RESPOND | OK |
| 6 | Jam berapa sekarang? | RESPOND | OK |
| 7 | 100 saja langsung. | ACK_ONLY | fragment/command |
| 8 | nomor berapa lagi? | RESPOND | OK |
| 9 | Berapa lagi? | RESPOND | OK |
| 10 | No. | ACK_ONLY | 2-char fragment |
| 11 | Gimana masa depan AI? | RESPOND | OK |
| 12 | , pesan tiket, cari hotel. | ACK_ONLY | **tail of a split utterance** |
| 13 | Tapi Play Store belum mengizinkan. | ACK_ONLY | continuation |
| 14 | Coba kamu cari dulu kenapa masalahnya. | RESPOND | OK |

Ungoverned partials (never reached BDV):

- `Kalau saya sih lebih lebih pengen AI itu bisa order Grab`
- `, Gojek`

So the user said one sentence about Grab/Gojek/tiket/hotel; Persona steered only the last clause as ACK_ONLY.

Questions with `?` → RESPOND. Clauses without question-shape → ACK_ONLY. Fallback-on-partial is the BDV miss, not a random timeout.

## RMS

Logged client RMS is **biased high** (bridge only prints interesting / cadence chunks).

- n=424, mean=0.056, median=0.043, max=**0.3034**, p90=0.106
- 91 chunks > 0.08, 52 > 0.10

Spikes sit **inside spoken windows**, not as isolated noise:

- #26–27 → Halo
- #107–109 → semuanya
- #231–238 → nomor satu (max 0.1535)
- **#1230–1236** (max 0.1108) → **Berapa lagi?**  ← the cited peak is speech
- #3799–3801 max **0.3034** → only plausible clap/clip; next line is still the hotel clause
- late session #3869–4020 → long utterance about AI / Play Store

Gemini-sent RMS median 0.0016 because those lines are mostly cadence (every 100 chunks), often silence/keepalive.

**Do not treat RMS > 0.08 as noise.** That threshold fires on almost every real word and would make ASR worse.

## Root causes (ordered)

1. **Audio gate vs S2S.** Gemini starts talking from the mic stream. Gate is SUPPRESS until steer lands, so the natural first reply is dropped. Steer text then sets `sc.interrupted`. Playback is no longer flushed, but Gemini still restarts. User hears a hole, then a second take.

2. **Final ASR never arrives in time — or at all.** `schedule_final_governance` only runs on `input_transcription.finished`. That log line never appears. Fallback `FALLBACK_IDLE_S=0.8` + first suppressed chunk fires instead. `turn_complete` is the better finalization signal; it was used once (`nomor satu`) and skipped the other 13 times because suppress-fallback already ran.

3. **Partials are governed as whole turns.** Growing ASR is not accumulated. Mid-sentence clauses become ACK_ONLY. The Grab sentence is the smoking gun.

4. **Audiogate hold** is the wait for steered PCM after the first reply was discarded. `seen=False` = steered audio has not started; that is a gap, not a leak of an open speaker for minutes. After engine audio starts, hold is normal.

## Mitigations (impact vs risk)

**P0 — stop dropping the first S2S reply.** For `RESPOND`/`ENGINE`, forward model audio as it arrives (constrain via system instruction / post-hoc BDV on the transcript). Do not inject steer text mid-utterance. Never cut the media track for orchestration.

**P0 — finalize on `turn_complete`, not on first suppress.** Disable `maybe_schedule_fallback_governance("suppressed_audio")` or raise idle far above typical barge of model audio (2–3 s). One fallback per utterance, only after mic idle **and** `turn_complete` (or `finished=true`).

**P1 — stitch partials.** Keep a rolling utterance buffer; only run BDV when `finished` or `turn_complete`. Do not govern `, Gojek` or `, pesan tiket…` as new turns.

**P1 — log enrichment.** Log `finished` as `true` / `false` / `None`; count suppressed bytes not just chunk totals; log gate-hold duration until first `forward mode=engine`.

**P2 — gate timeout.** If `awaiting_steered_turn` and no forwarded audio for ~1.5 s, nudge or close. Do not leave `seen=False` unbounded.

**Skip:** RMS>0.08 noisy-chunk handler. Skip raising ASR confidence on spikes. Those peaks are the user’s voice.

## Verify after a fix

Success log for one user question should look like:

- `user transcript partial` → (optional) `user transcript final` **or** `turn_complete`
- `governance applied … play_steered=True`
- `forward model audio … mode=engine` **without** a preceding burst of `suppressed ungoverned` on that same turn
- no `queue transcript while answer plays` for the same sentence split into three partials
