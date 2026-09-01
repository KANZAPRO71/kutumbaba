# Persona AI — Implementation Roadmap v1

**Status:** Draft v1.0 — reality decomposition plan  
**Terakhir diperbarui:** 2026-08-26  
**Prinsip:** Bukan feature roadmap — **apa yang kita buang/suppress supaya sistem hidup di runtime nyata.**

Spec lengkap tetap di docs/ — roadmap ini mendefinisikan **subset yang di-build** per fase.

---

## One line

Roadmap = path dari **spesifikasi kognitif lengkap** → **runtime yang bisa jalan** — text-first, latency-aware, mobile-viable.

---

## Design ceiling → implementation floor

| Spec (ideal) | Runtime v1 (real) |
|--------------|-------------------|
| 13-step logical pipeline | **3–5 hot-path steps** per execution profile |
| Full OAL + CQF + CPS + arc decay | **Behavior decide + hard rules**; feedback async |
| 6 silence types | **4 actions:** SILENCE, DEFER, ACK, RESPOND |
| Coherence + controlled drift | **Coherence bind**; drift allowance **off** until v1.1 |
| Memory 5 types + decay | **Working + semantic** in-memory; commit async |
| Voice real-time | **Text MVP**; voice = transport plug-in v2 |
| Probabilistic sample_tempered | **argmax** in v1 (reproducible, debuggable) |

> **Rule:** Spec docs tidak dihapus. Implementasi v1 = **intentional subset**.

---

## Runtime reality constraints

### Latency budget (text channel)

| Segment | Target v1 | Notes |
|---------|-----------|-------|
| behavior.decide() | < 30 ms | Pure Python rules, no LLM |
| arc.load + coherence.bind | < 10 ms | In-memory |
| memory.retrieve (working) | < 15 ms | Skip for whisper/ghost |
| LLM | 500–2000 ms | Dominates — **minimize pre-LLM work** |
| policy.post_check | < 20 ms | Regex + denylist |
| **Total pre-LLM** | **< 80 ms** | Non-negotiable for snappy feel |

**13-step flow** = logical order. **Hot path** = profile-dependent skip (ARCHITECTURE adaptive execution).

### Voice (deferred complexity)

Real-time voice cannot run full pipeline per partial utterance.

| v1 text | v2 voice |
|---------|----------|
| Turn = complete message | Turn = VAD-segmented |
| DEFER on pause = state flag | DEFER integrated with STT stream |
| Single LLM call | Streaming LLM + barge-in |

Transport (Retell / LiveKit / WebRTC) = **below** Persona AI. Integration: inject BDV before LLM in transport's agent hook.

### Mobile / edge

| Constraint | v1 approach |
|------------|-------------|
| Memory footprint | In-memory store; no vector DB on device |
| Background session | Session + arc persist to SQLite/local |
| Offline | Not supported v1 — graceful degrade message |
| Battery | No continuous inference — event-driven turns only |

### Weak signal instability (CQF × CPS × memory bias)

**v1 mitigation:** Single bias cap already in spec (memory ≤ 0.10). **Additionally in v1 runtime:**

- CQF/CPS computed **post-turn async** — do not feed same-turn OAL
- Disable `cqf_rolling` arc preference until ≥50 eval turns logged
- Memory signals only when `retrieve` returns ≥1 high-confidence record

---

## Evolution path

```
v0 — Proof of cognition     Behavior + BDV + early exit (no LLM)
v1 — MVP text companion     Full text pipeline, simplified internals
v2 — Continuity + voice     Memory persist, coherence drift, STT/TTS
v3 — Platform               Plugins, multi-persona, eval pipeline
```

---

## v0 — Proof of cognition (2–3 weeks)

**Goal:** Buktikan **"AI bisa tidak menjawab"** tanpa LLM.

### Build

| Module | Scope |
|--------|-------|
| core | BDV types, Turn, SessionContext |
| behavior | `decide()` only — pressure formulas, argmax, **no** feedback/CQF/CPS |
| arc | load/save in-memory; phase only — **no** decay v0 |
| session | Minimal context |
| tests | Scenarios A–D from BEHAVIOR_ENGINE |

### Cut from spec

- OAL tier 2–3 merge (use priority list only)
- CQF, CPS feedback loop, probabilistic sampling
- Full silence taxonomy (6 → 4 actions)
- LLM (until v0.4)

### Minimum expressivity floor (v0 — MUST NOT remove)

Aggressive cutting risks a **mechanical minimal brain**. v0 keeps three alive layers:

| Floor | What stays on | Why |
|-------|---------------|-----|
| **Coherence tone clamp (light)** | `coherence.bind()` — warmth clamp, single voice fragment | Prevents flat/robotic output shape |
| **Personality micro-weighting** | `personality.apply()` — trait warmth bias on BDV tone | System still "has a voice" |
| **Arc minimal hint** | `relational_warmth` + phase → tone/ack bias in decide | Trajectory felt even without memory |

Controlled drift, CQF loop, full CPS gradient — still **OFF**. Floor ≠ full spec.

### v0 implementation phases

| Phase | Deliverable |
|-------|-------------|
| **0.1** | `decide()` → BDV, early exit, tests |
| **0.2** | personality light + tone clamp |
| **0.3** | coherence soft bind → VoiceDirective |
| **0.4** | LLM adapter + CPS async log (defer if needed) |

### Exit criteria

- [x] "Oke" after long msg → SILENCE, llm_called=false
- [x] Vent → ACK_ONLY
- [x] Direct Q → RESPOND
- [x] All decisions logged with reason_codes (via `BehaviorReasoning`)

---

## v1 — MVP text companion (4–6 weeks)

**Goal:** End-to-end text — feels like friend, not chatbot — **on simplified stack**.

### Minimum viable cognition stack (MVCS)

```
session → behavior.decide → [early exit]
       → personality.apply (light)
       → coherence.bind (stability only — no controlled drift)
       → policy.pre/post (minimal denylist)
       → llm.complete
       → behavior.feedback (CPS regex only — no full CQF)
       → arc.save
```

### Build

| Module | v1 scope |
|--------|----------|
| conversation | Orchestrator + execution profiles (ghost/whisper/standard) |
| personality | Traits + BDV length/tone mapping |
| coherence | bind() + identity clamp — **no** verify_voice rewrite loop |
| policy | FP1 denylist + 5 hard rules; Tier-0 must_respond config-only |
| llm | One adapter (OpenAI or Gemini) |
| behavior feedback | CPS regex (CP1–CP5); CQF log only, **no** rolling bias |
| arc | warmth/trust numeric; **linear** decay (skip exponential v1) |
| memory | working buffer only; optional semantic if explicit "ingat ya" |

### Simplify (spec → v1 code)

| Spec feature | v1 simplification |
|--------------|-------------------|
| OAL full merge | Tier 0 policy + urgency override + argmax |
| 6 silence types | Enum stored but 4 execution paths |
| Controlled drift | **Disabled** (`imperfection_budget=0`) |
| CQF composite | Log N/S/F/A; no auto-tune |
| Memory decay half-lives | TTL delete only (no formula) |
| Coherence verify_voice | Log score; no rewrite trigger |
| Plugin system | **Stub registry** — no hooks |

### Defer to v1.5 / v2

- Arc exponential decay + emotional volatility
- CQF rolling → arc quieter bias
- Memory episodic/relational + DB persistence
- Coherence controlled drift allowance
- personality presence profile full
- policy PII classifier (manual tags v1)
- speech/STT/TTS
- sample_tempered production mode
- External eval / thumbs feedback loop

### Remove from v1 runtime (not deleted from spec)

| Removed | Why |
|---------|-----|
| Same-turn CQF → next-turn bias | Instability; needs data |
| Full 10-pattern CPS gradient | Regex subset sufficient MVP |
| Memory pressure bias > 0.05 | Reduce cross-layer noise v1 |
| LLM-based memory extraction | Rule-based explicit remember only |
| Multi-adapter LLM | One provider until stable |

### Exit criteria

- [ ] Side-by-side: prompt-only vs Persona pipeline on 10 scenarios — internal eval ≥ 7/10 human feel
- [ ] Pre-LLM latency p95 < 80 ms (excl. LLM)
- [ ] Zero "Ada lagi yang bisa bantu?" in 100-turn test
- [ ] SILENCE on closure ≥ 90% correct
- [ ] Single persona configurable via JSON profile

---

## v1.5 — Continuity (2–3 weeks)

- Memory: semantic + preference persist (SQLite)
- Episodic summary on session end (async LLM job)
- Arc decay formulas from spec §8.6
- Memory signals (capped bias)

---

## v2 — Voice + polish (4+ weeks)

- Execution profile integration with STT partial results
- DEFER / SILENCE_STRATEGIC with voice pause signals
- TTS prosody from BDV.timing
- Transport adapter (Retell agent hook or LiveKit node)
- Coherence controlled drift enabled
- CQF rolling with manual review gate (not auto bias until validated)

---

## v3 — Platform

- Plugin hooks live
- Multi-persona
- Vector retrieval for memory
- Eval pipeline (external truth → CQF calibration)
- Second LLM adapter

---

## What breaks in real runtime (honest list)

| Problem | Symptom | v1 mitigation |
|---------|---------|---------------|
| Pipeline too deep | "Processed" feel, slow ack | whisper profile + templates |
| LLM ignores constraints | Long chatbot reply | policy rewrite once + word cap |
| Over-silence | User feels ignored | stability min_engagement (behavior) |
| Over-talk | Chatbot habits | CPS CP1–CP5 block |
| Memory false fact | Wrong callback | write policy: explicit only v1 |
| Arc/game-ui bars | Trust feels fake | defer trust UI; log internal only |
| Mobile cold start | Slow first turn | preload session + arc at connect |
| Voice latency | Interrupt fails | **defer v2** — text prove first |

---

## Integration boundary (production stacks)

Persona AI = **behavior decision layer** — not transport.

```
[CallRail / Web / Mobile]
        ↓
[Retell | LiveKit | custom WS]  ← turn detection, audio
        ↓
Persona AI: decide → BDV → (optional LLM)
        ↓
[TTS / text response]
```

---

## Team / agent implementation order

For dev agents — **strict sequence**, no parallel feature creep:

1. v0 behavior tests pass
2. conversation ghost/whisper/standard paths
3. llm wire with VoiceDirective
4. policy post-check
5. CPS regex feedback
6. memory working buffer
7. v1 exit criteria eval

**Do not** implement full BEHAVIOR_ENGINE v1.3 in one pass.

---

## Success metrics (real usage — not spec proxy)

| Metric | v1 target | How measured |
|--------|-----------|--------------|
| Unprompted question rate after vent | < 5% | Log scan |
| Closure silence correctness | ≥ 90% | Scenario suite |
| Avg pre-LLM ms | < 80 | Telemetry |
| User repeat ("hello?") rate | < 2% per session | Log |
| Chatbot phrase detection | 0 CP1 in eval set | CPS regex |

CQF remains **internal log** until external eval pipeline exists (v2+).

---

## Doc map (spec frozen — implementation follows this roadmap)

| Doc | Role |
|-----|------|
| [VISION.md](VISION.md) | Why |
| [BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md) | Full behavior spec (implement subset per phase) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Module boundaries |
| [PERSONALITY.md](PERSONALITY.md) | Expression |
| [COHERENCE.md](COHERENCE.md) | Unity |
| [CONVERSATION_POLICY.md](CONVERSATION_POLICY.md) | Hard gate |
| [MEMORY.md](MEMORY.md) | Continuity |
| **ROADMAP.md** (this) | **What actually ships when** |

---

## North star for implementation

> Ship the **smallest stack** that proves: *"bukan mesin yang selalu merespons"* — then add depth only with runtime evidence.

When in doubt: **cut, don't add.**
