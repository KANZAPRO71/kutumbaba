# Memory Engine — Specification v1

**Status:** Draft v1.0  
**Terakhir diperbarui:** 2026-08-26  
**Referensi:** [ARCHITECTURE.md](ARCHITECTURE.md) · [BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md) · [COHERENCE.md](COHERENCE.md)

---

## One line

Memory = **identity continuity across time** — what the persona *knows* about the user, bukan *bagaimana percakapan berjalan* (arc) atau *apa yang harus dilakukan* (behavior).

> Tanpa memory: sistem pintar ngobrol tapi **tidak mengenal**. Dengan memory: "oh iya, kamu kan yang kemarin bilang..."

---

## Arc vs Memory (locked)

| | Arc Engine | Memory Engine |
|---|------------|---------------|
| **Stores** | Trajectory: phase, warmth, trust, drift | Facts, preferences, relational patterns |
| **Horizon** | Session (+ short carry) | Cross-session persistent |
| **Question** | "Bagaimana percakapan *sekarang*?" | "Apa yang kita *tahu* tentang user?" |
| **Mutated by** | Behavior feedback | Memory commit pipeline |
| **Influences** | BDV via arc preferences (pre-arbitration) | Pressure bias, arc depth hint, personality nuance |

**Never merge.** Arc emotional state ≠ memory fact.

---

## Three questions (v1 contract)

### 1. What IS stored?

| Type | Content | Example |
|------|---------|---------|
| **Semantic** | Stable facts about user | "Kerja di startup", "Punya anak 2 tahun" |
| **Preference** | Stated likes/dislikes, comms prefs | "Suka jawaban singkat", "Tidak suka emoji" |
| **Relational** | Stable interaction patterns | "Often vents about work Monday", "Prefers ack over advice" |
| **Episodic** | Compressed past-session summaries | "Last week discussed job offer" |
| **Working** | Current session turn buffer | Last N turns verbatim/summary |

### 2. What is NOT stored?

| ❌ Not in memory | Owner |
|-----------------|-------|
| Transient emotion this turn | Arc / behavior interpret |
| CPS, CQF, arbitration traces | Behavior (internal) |
| Arc phase, warmth, trust values | Arc |
| BDV decisions | Behavior logs only |
| Raw LLM drafts | Ephemeral |
| Inferred psychology / diagnosis | Forbidden |
| Single-turn vent as permanent fact | Rejected at write |
| Policy violation content | Policy audit only |

**Rule:** Memory stores **what user said or explicitly confirmed** — not what system inferred about their soul.

### 3. How memory affects the system?

| Target | Influence | Override BDV? |
|--------|-----------|---------------|
| **Behavior** | `MemorySignals` → pressure bias only | **Never** |
| **Arc** | `relational_depth` hint on load | **Never** |
| **Personality** | Optional shared-history reference flag | **Never** |
| **LLM** | Retrieved facts in context | Under BDV + VoiceDirective caps |
| **Coherence** | No direct path | — |
| **Policy** | PII scope for pre-check | — |

```
Memory → MemorySignals (soft bias)
       → MemoryBundle (LLM context)
       ≠ BDV mutation
```

---

## Memory record schema

```yaml
MemoryRecord:
  id: uuid
  user_id: string
  persona_id: string

  type: semantic | preference | relational | episodic
  content: string                  # normalized fact — one claim per record
  confidence: float                # 0.0–1.0 write confidence

  source:
    turn_id: uuid
    session_id: uuid
    extraction: user_explicit | user_confirmed | plugin | summary

  sensitivity: public | personal | sensitive    # PII tier
  created_at: datetime
  updated_at: datetime
  expires_at: datetime | null
  contradicted: bool
```

**Working memory** (separate, not persisted long-term):

```yaml
WorkingMemory:
  session_id: uuid
  turns: Turn[]                    # max 20
  rolling_summary: string | null   # updated every 5 turns
```

---

## Write policy

### When to write

| Trigger | Type | Min confidence |
|---------|------|----------------|
| User: "Ingat ya, ..." / "Remember..." | semantic / preference | 0.95 |
| Same fact stated ≥2 times | semantic | 0.75 |
| Explicit preference ("jangan panjang-panjang") | preference | 0.85 |
| Plugin validated extraction | semantic | 0.80 |
| Session end summary job | episodic | 0.70 |
| Stable pattern ≥3 sessions (relational detector) | relational | 0.65 |

### When NOT to write

- Single emotional vent ("capek banget hari ini") → arc handles; **no memory commit**
- Assistant-generated content
- Low-confidence NER guess
- Contradicts existing record without user confirmation → mark old `contradicted`, do not auto-merge
- Sensitive inference ("user seems depressed") → **forbidden**

### Write pipeline

```
Turn completed
  → extract candidates (rules + optional LLM extractor — async)
  → filter through WritePolicy
  → dedupe / contradiction check
  → persist MemoryRecord
  → emit memory.committed event
```

**Async OK** — memory commit must not block turn latency.

### Contradiction handling

```
New: "Sekarang kerja di B"
Old: "Kerja di A" (semantic, same slot: employer)

→ Old.contradicted = true
→ New record created
→ retrieval prefers latest non-contradicted
```

---

## Decay policy

| Type | TTL / decay | Notes |
|------|-------------|-------|
| **Working** | Session end | Deleted on session close |
| **Episodic** | half-life 45 days | Summaries fade |
| **Relational** | half-life 90 days | Re-learn if pattern continues |
| **Preference** | half-life 180 days | Refresh on re-mention |
| **Semantic** | half-life 365 days OR until contradicted | Long-lived facts |

```
effective_confidence = confidence * exp(-ln(2) * age_days / half_life_type)
```

Retrieve threshold: `effective_confidence >= 0.35` (configurable).

**User delete:** `forget(record_id)` / `forget_category()` — immediate removal (privacy).

---

## Retrieval

### API

```
retrieve(user_id, persona_id, query, scopes[]) → MemoryBundle
commit(user_id, turn, candidates[]) → CommitResult   # async
forget(user_id, filter) → void
```

### Scopes (map to execution profile)

| Scope | Content | Profile |
|-------|---------|---------|
| `working` | Turn buffer + rolling summary | whisper, standard+ |
| `episodic` | Past session summaries | standard, presence, focused |
| `semantic` | Facts | presence, focused |
| `preference` | Prefs | all except ghost |
| `relational` | Patterns | presence, focused |

```yaml
MemoryBundle:
  records: MemoryRecord[]
  working: WorkingMemory | null
  retrieval_query: string
  token_budget: int                # hard cap for LLM injection
```

Retrieval ranks by: relevance to query × effective_confidence × recency.

---

## Influence signals (soft — never override BDV)

After retrieve, memory emits **`MemorySignals`** consumed by behavior at `decide()` — same pattern as `PolicySignal`, **lower authority**.

```yaml
MemorySignals:
  pressure_bias:
    user_expectation: float       # +0.05 if user references known fact expecting continuity
    social_greeting: float        # +0.03 if returning user with episodic hit
  arc_hint:
    relational_depth: float       # 0–1, grows with cross-session record count
  personality_hint:
    reference_shared_history: bool   # allow subtle callback, not forced
  plugin_context: []              # domain memory enrichments
```

**Application (behavior side):**

```
speak_pressure += 0.05 * memory.pressure_bias.user_expectation
# Capped: total memory bias ≤ 0.10 on any pressure dimension
# OAL + stability unchanged — memory cannot trigger must_respond
```

**Personality:** if `reference_shared_history` and BDV allows NORMAL+ → add optional prompt fragment: "You may briefly reference shared history if natural — do not force."

**Arc:** on `arc.load()`, apply `relational_depth` as read-only initializer — does not overwrite warmth/trust computed by arc decay.

---

## Privacy-safe structure

```yaml
PrivacyConfig:
  default_sensitivity: personal
  pii_fields: [phone, email, address, id_number]   # auto-tag sensitive
  retrieval_redaction: mask | omit | full           # per sensitivity tier
  export_enabled: bool                              # future user API
  retention_max_days: 365                           # global cap
```

| Tier | Retrieval to LLM | Log |
|------|------------------|-----|
| public | full | full |
| personal | full in private session | hashed id only |
| sensitive | masked ("[phone]") unless policy allows | never content |

**Policy integration:** `pre_check` receives memory PII flags → sets `pii_handling` mode.

**Forbidden in logs:** sensitive record content in production info-level logs.

---

## Cross-session continuity

```
Session start:
  memory.retrieve(scopes=[preference, relational, episodic top-k])
  → MemorySignals + optional greeting bias (behavior, capped)

During session:
  working memory updated every turn
  async commit on extractable facts

Session end:
  episodic summary job → new episodic record
  working memory cleared
```

**Trust growth:** Arc owns trust signal per session. Memory provides **depth** ("kita pernah ngobrol tentang X") — complementary, not duplicate.

---

## Pipeline placement

```
[profile-dependent]
memory.retrieve() → MemoryBundle + MemorySignals
memory signals → behavior.decide() input (with policy signals)

... LLM uses MemoryBundle in context ...

turn end:
memory.commit() [async]
```

Ghost profile: skip retrieve. Whisper: working only. Focused: all scopes.

---

## Module design

```
src/persona_ai/memory/
├── store/           # persistence interface (in-memory v1, DB later)
├── retrieve/        # ranking, scopes, token budget
├── write/           # WritePolicy, contradiction, decay
├── extract/         # candidate extraction (rules v1, LLM optional v2)
└── engine.py        # retrieve(), commit(), forget()
```

**Depends on:** `core` only.  
**Must NOT:** import behavior, arc internals, llm (extractor v2 via injected port).

---

## Examples

### Explicit remember

```
User: "Ingat ya, aku allergic seafood."

Write: semantic, confidence 0.95, sensitivity personal
Next session retrieve: included in bundle
MemorySignals: user_expectation +0.05 if user asks restaurant recommendation
BDV: unchanged authority — behavior may RESPOND with allergy-aware answer
```

### Vent — NOT stored

```
User: "Ah capek banget hari ini"

Write: rejected (transient emotional, single turn)
Arc: emotional drift updated
Memory: no commit
```

### Relational pattern (3 sessions)

```
Pattern detected: user often Monday vent about work

Write: relational, confidence 0.68
Retrieve: personality_hint reference_shared_history on Monday presence profile
BDV: still from behavior — maybe ACK bias via arc+pressure, not memory override
```

---

## Testing checklist

- [ ] Vent single-turn not persisted
- [ ] Explicit "ingat ya" → semantic with high confidence
- [ ] Contradiction marks old record, retrieves new
- [ ] Memory bias capped ≤0.10 on pressure — never changes speak action alone
- [ ] Arc fields not stored in memory records
- [ ] CPS/CQF not in memory store
- [ ] Sensitive tier masked per PrivacyConfig
- [ ] Working cleared on session end
- [ ] ghost profile skips retrieve

---

## Related docs

| Doc | Relasi |
|-----|--------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Pipeline step 5, arc vs memory |
| [BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md) | MemorySignals pressure bias cap |
| [CONVERSATION_POLICY.md](CONVERSATION_POLICY.md) | PII handling |
| ROADMAP.md | Persistence backend (next) |
