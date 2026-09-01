# Persona AI — Architecture v1

**Status:** v1.1 — + adaptive pipeline execution  
**Prinsip:** Simplify & map. **Tidak** menambah konsep baru — hanya orchestrate.

---

## One line

Persona AI = **behavior-driven conversation runtime** — satu orchestrator linear, modul dengan boundary jelas, **BDV** sebagai satu-satunya keputusan perilaku antar modul.

---

## Runtime mantra

```
1 request → 1 decision (BDV) → 1 output → 1 feedback update
```

Conversation engine **routing saja**. Intelligence hidup di modul — **tidak di-orchestrator**.

---

## System map

```
                    ┌─────────────────┐
                    │  API / Channel  │  (future — out of scope v1)
                    └────────┬────────┘
                             │ TurnRequest
                             ▼
                    ┌─────────────────┐
                    │ Session Manager │
                    └────────┬────────┘
                             │ SessionContext
                             ▼
┌────────────────────────────────────────────────────────────┐
│              CONVERSATION ENGINE (orchestrator)            │
│  linear pipeline — no business logic                       │
└──┬──┬──┬──┬──┬──┬──┬──┬──┬────────────────────────────────┘
   │  │  │  │  │  │  │  │  │
   ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼
 Speech Behavior Arc Memory Policy Personality LLM Plugins
 (opt)  ★      │    (facts) (hard)  (voice)  (swap) (domain)
              │
              └── Arc Engine: trajectory state ONLY
                  Behavior Engine: calls Arc, owns OAL/CQF/CPS
```

---

## Module responsibility matrix

| Module | Owns | Does NOT own |
|--------|------|--------------|
| **core** | Types, contracts, BDV schema, events | Any logic |
| **session** | Session lifecycle, `SessionContext` | Decisions, memory content |
| **conversation** | Pipeline order, DI wiring, early exit routing | Pressure, CQF, prompts |
| **behavior** ★ | Decision loop, OAL, stability, CQF, CPS → **BDV** | Arc persistence, facts, LLM |
| **arc** | `ConversationArc` load/save/decay | Decisions, user facts |
| **memory** | User/persona **facts** retrieve/commit | Trajectory, emotional drift |
| **policy** | Hard rules, pre/post check, Tier-0 signals to OAL | speak decision, voice binding |
| **personality** | Profile → expression draft | When to speak, BDV mutation |
| **coherence** | BDV + expression + arc → **VoiceDirective** | speak decision, safety, CQF |
| **llm** | Provider adapter, `complete()` | Constraints content |
| **speech** | STT/TTS (optional) | Behavior |
| **plugins** | Domain hooks → signals | Core pipeline |

### Arc vs Memory (critical separation)

| | Arc Engine | Memory Engine |
|---|------------|---------------|
| **Stores** | Phase, warmth, trust, drift, threads | Facts, preferences, episodic summaries |
| **Question** | "Bagaimana percakapan berjalan?" | "Apa yang kita tahu tentang user?" |
| **Mutated by** | Behavior feedback loop | Memory commit (async OK) |
| **Spec** | BEHAVIOR §8 | [MEMORY.md](MEMORY.md) |

---

## Folder structure (final v1)

```
Persona_Ai/
├── docs/
│   ├── VISION.md
│   ├── ARCHITECTURE.md          ← this file
│   ├── BEHAVIOR_ENGINE.md       ← spec (do not duplicate in code comments)
│   ├── MODULES.md               ← interface contracts
│   └── ...
├── src/persona_ai/
│   ├── core/
│   │   ├── types/               # Message, Turn, BDV, SessionContext
│   │   ├── contracts/           # ABC per module
│   │   └── events/
│   ├── session/
│   ├── conversation/            # orchestrator only
│   ├── behavior/                # decision runtime
│   │   ├── interpret/
│   │   ├── pressure/
│   │   ├── arbitration/         # OAL + stability
│   │   ├── quality/             # CQF + CPS (internal)
│   │   └── engine.py            # decide() + feedback()
│   ├── arc/                     # trajectory state store
│   ├── memory/
│   ├── policy/
│   ├── personality/
│   ├── coherence/               # identity binding → VoiceDirective
│   ├── llm/
│   │   └── providers/
│   ├── speech/
│   └── plugins/
└── tests/
    ├── behavior/
    ├── arc/
    └── conversation/            # pipeline integration
```

**Rule:** CQF / CPS / OAL / pressure formulas live **only** under `behavior/`. Arc formulas (decay) live **only** under `arc/`. Orchestrator **imports neither formula**.

---

## Runtime flow (linear)

```
TurnRequest
│
├─1─ session.get_context(session_id) → SessionContext
│
├─2─ [channel=voice] speech.transcribe(audio) → text
│
├─3─ arc.load(session_id) → ConversationArc
│
├─4─ behavior.decide(input, context, arc, signals) → BehaviorDirectiveVector
│       │  (internally: interpret → pressure → softmax → OAL → BDV)
│       │  spec: BEHAVIOR_ENGINE.md — not reimplemented elsewhere
│       │
│       ├─ BDV.speak ∈ {SILENCE, DEFER} → skip to step 10 (no LLM)
│       └─ continue
│
├─5─ memory.retrieve(session_id, query, scopes) → MemoryBundle
│
├─6─ policy.pre_check(input, BDV, memory) → PolicyConstraints
│
├─7─ personality.apply(profile, BDV) → ExpressionConstraints
│
├─7b─ coherence.bind(bdv, expression, arc, anchor) → VoiceDirective
│       │  identity stability · cross-layer merge · single voice
│       │  spec: COHERENCE.md — does NOT change speak/question_budget
│
├─8─ plugins.on_llm_context(context) → tools, enrichments
│
├─9─ llm.complete(LLMRequest.from(BDV, voice_directive, memory, policy))
│       │
│       ├─ policy.post_check(draft) → approved | rewrite
│       └─ coherence.verify_voice(draft, voice_directive) → ok | tighten_rewrite
│
├─10─ [channel=voice] speech.synthesize(text, BDV.timing)
│
├─11─ behavior.feedback(output, BDV, arc) → QualitySnapshot
│       │  (CQF, CPS — updates arc in-memory)
│       └─ arc.save(session_id, arc)
│
├─12─ memory.commit(session_id, turn) [async OK]
│
└─13─ session.record_turn(session_id, TurnResult) → TurnResult
```

**Early exit (step 4):** `SILENCE` / `DEFER` → step 11 (feedback with empty/minimal output) → 13. **No LLM.**

Diagram above = **logical order**. Runtime uses **adaptive execution** below — not every step runs every turn.

---

## Adaptive pipeline execution (soft boundaries)

Linear **≠** rigid. Orchestrator selects an **execution profile** from BDV after step 4 — skips stages that would add latency or "processed" feel without value.

> **Goal:** experiential continuity — respons **mengalir**, bukan terasa diproses stage-by-stage.

### Execution profiles

| Profile | Trigger | Execution |
|---------|---------|-----------|
| **ghost** | `speak` = SILENCE \| DEFER | Steps 11→13 only. No LLM, personality, memory, policy gen. |
| **whisper** | `speak` = ACK_ONLY · minimal · low engagement | Template/micro-LLM. Coherence **bind** template only. |
| **standard** | `speak` = RESPOND · NORMAL | Full pipeline incl. coherence bind |
| **presence** | `engagement` ≥ 0.65 OR `tone_shift` ∈ {WARMER, SOFTER} | Full pipeline + personality **full** mode + arc snapshot passed to personality (read-only). Memory: working + episodic. |
| **focused** | `length` = EXPAND · direct question | Full pipeline + memory all scopes. Plugins tools enabled. |

```yaml
ExecutionProfile:
  name: ghost | whisper | standard | presence | focused
  skip: [memory, personality, llm, plugins, ...]
  llm_mode: none | micro | full
  personality_mode: bypass | light | full
  memory_scopes: [] | [working] | [working, episodic] | all
```

### Profile selection (deterministic)

```
IF speak IN (SILENCE, DEFER)           → ghost
ELIF speak = ACK_ONLY AND length = MINIMAL AND engagement < 0.45 → whisper
ELIF length = EXPAND AND intent_need >= 0.6 → focused
ELIF engagement >= 0.65 OR tone_shift != STABLE → presence
ELSE                                   → standard
```

### Why this matters

| Without adaptive execution | With adaptive execution |
|----------------------------|-------------------------|
| ACK runs full LLM + memory | Whisper: instant, human-paced |
| Silence still hits policy+LLM path | Ghost: zero generation overhead |
| Every turn feels "pipelined" | High-engagement turns get richness **when BDV says so** |

**Rule:** Profile selection reads **BDV only** — no second decision brain in conversation engine.

---

## Data contracts

### TurnRequest (in)

```yaml
session_id: uuid
turn_id: uuid
channel: text | voice
input:
  text: string
  audio_ref: optional
metadata:
  received_at: datetime
```

### BehaviorDirectiveVector (BDV) — behavior → everyone

Satu objek keputusan. **Full schema:** BEHAVIOR_ENGINE §18.

```yaml
# Minimum fields other modules need:
speak: RESPOND | SILENCE | DEFER | ACK_ONLY
silence_type: optional
engagement_level: float
length: MINIMAL | NORMAL | EXPAND
questions: NONE | CLARIFY_ONLY | ALLOWED
question_budget: int
tone_shift: STABLE | WARMER | SOFTER | MATCH_USER
partial_response: bool
timing: { delay_ms: int }
stop_rule: ONE_TURN | UNTIL_RESOLVED
```

Downstream **consumes BDV** — tidak membaca pressure/CQF/CPS/arbitration internals.

### LLMRequest (conversation → llm)

```yaml
behavior: BDV                         # action authority — frozen
voice: VoiceDirective                 # from coherence — unified expression
memory: MemoryBundle
policy: PolicyConstraints
messages: Message[]
tools: ToolDefinition[]
model: string
```

Coherence produces **VoiceDirective** — single voice input for LLM. Personality output is intermediate only.

### TurnResult (out)

```yaml
turn_id: uuid
output:
  text: string | null
  audio_ref: optional
bdv: BehaviorDirectiveVector
quality: QualitySnapshot         # internal — for logging, not user
llm_called: bool
latency_ms: int
```

---

## Dependency rules

```
core ← everything
arc ← behavior (load/save only), conversation (via behavior)
behavior ← arc, core          # NO llm, NO memory content logic
memory ← core
policy ← core
personality ← core
coherence ← core
llm ← core
speech ← core
plugins ← core
conversation ← all (DI only)
```

| Forbidden import | Why |
|------------------|-----|
| behavior → llm | Decision before generation |
| behavior → memory | Facts ≠ trajectory |
| arc → behavior | One direction |
| personality → llm | Composition in conversation |
| coherence → behavior | One direction — coherence reads BDV as data |
| policy re-deciding speak/silence | Behavior authority |
| plugins → conversation | Inverse via registry |
| Any module re-implementing CQF/CPS/OAL | Single owner: behavior |

---

## Behavior Engine internal map (reference only)

Subfolders under `behavior/` map to BEHAVIOR spec — **one module, one runtime package**:

| Package | Spec section | Runtime role |
|---------|--------------|--------------|
| `interpret/` | §2 step 1 | Intent depth |
| `pressure/` | §3 | U, E, M, X, A formulas |
| `inertia/` | §5 | P_continue, P_stop |
| `arbitration/` | §16, §17 | OAL + stability |
| `quality/` | §9, §10 | CQF, CPS (feedback only) |
| `engine.py` | §2 loop | `decide()`, `feedback()` |

Arc decay (§8.6) → **`arc/decay.py`**, called by `arc.load()` and after `behavior.feedback()`.

---

## Orchestrator responsibilities (conversation/)

**Only these jobs:**

1. Resolve **execution profile** from BDV (adaptive pipeline §)
2. Call modules per profile — not blind full pipeline every turn
3. Assemble `LLMRequest` when profile includes LLM
4. Emit events (`TurnStarted`, `BDVResolved`, `TurnCompleted`)
5. Inject dependencies — no static imports of provider SDKs

**Never in conversation/:** pressure math, CQF, arc decay, prompt templates.

---

## Debugging & observability

One log line per turn — flat, predictable:

```yaml
turn:
  id: uuid
  bdv.speak: ACK_ONLY
  bdv.engagement: 0.42
  arc.phase: deepening
  arc.warmth: 0.55
  llm_called: false
  quality.cqf: 0.84          # internal
  arbitration.winner: weighted  # internal
  stability.triggers: []
  latency_ms: 38
```

Tune behavior → read `behavior/` logs + BEHAVIOR spec.  
Tune arc dynamics → read `arc/` + BEHAVIOR §8.  
**Never** debug CQF in conversation engine — wrong layer.

---

## Implementation order

See **[ROADMAP.md](ROADMAP.md)** for v0→v1→v2 reality decomposition. Summary:

| Phase | Focus |
|-------|-------|
| v0 | behavior.decide + early exit, no LLM |
| v1 | text MVP, simplified stack |
| v2 | memory persist, voice, drift |

Architectural dependency diagram unchanged — roadmap defines **scope per phase**.

---

## What this doc deliberately excludes

- New scoring systems or layers
- Personality / policy / memory spec detail → separate docs
- API layer, deployment, database choice → ROADMAP.md
- BEHAVIOR formulas → [BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md) only

---

## Related docs

| Doc | Purpose |
|-----|---------|
| [VISION.md](VISION.md) | Why |
| [BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md) | Behavior spec (v1.3 locked) |
| [MODULES.md](MODULES.md) | Interface signatures |
| [PERSONALITY.md](PERSONALITY.md) | BDV → expression draft |
| [COHERENCE.md](COHERENCE.md) | Identity binding → VoiceDirective |
| [CONVERSATION_POLICY.md](CONVERSATION_POLICY.md) | Hard gate |
