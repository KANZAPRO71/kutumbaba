# Coherence Layer — Specification v1

**Status:** Draft v1.1 — + controlled drift allowance  
**Terakhir diperbarui:** 2026-08-26  
**Referensi:** [ARCHITECTURE.md](ARCHITECTURE.md) · [PERSONALITY.md](PERSONALITY.md) · [BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md)

---

## One line

Coherence Layer = **identity glue** — memastikan BDV, personality, dan arc terasa seperti **satu entitas**, bukan keputusan berlapis.

> Bukan behavior engine kedua. Bukan policy. **Binding layer** ringan sebelum dan sesudah generation.

---

## Authority hierarchy (locked)

```
Behavior (BDV)     → IF / WHEN / HOW MUCH to speak     [authority: action]
Personality        → HOW it should sound (draft)       [authority: voice draft]
Coherence          → ONE unified voice directive       [authority: identity binding]
Policy             → MUST NOT / safety / legal         [authority: hard gate]
LLM                → fill text under unified directive
```

| Layer | May change `speak`? | May change safety rules? |
|-------|---------------------|--------------------------|
| Behavior | ✅ | ❌ |
| Personality | ❌ | ❌ |
| **Coherence** | **❌** | **❌** |
| Policy | ❌ (only block/rewrite) | ✅ |

**Coherence never re-opens:** silence vs respond, question budget, or policy forbidden content.

---

## Problem it solves

**Layer fragmentation drift** — gejala:

- Respons benar secara rule tapi terasa potongan-potongan
- Tone bagus tapi timing aneh
- Arc emosional peak tapi expression terlalu dingin (or sebaliknya)
- Session tone loncat turn-to-turn

Penyebab: personality, arc hint, dan BDV each optimize locally. Coherence **binds** them into one `VoiceDirective`.

---

## Three components (minimal)

### 1. Identity Stability Rule

Menjaga persona **tetap recognizable** across session.

```yaml
IdentityAnchor:
  persona_id: string
  session_tone_baseline: float       # EMA of effective_warmth
  max_tone_drift_per_turn: 0.12      # clamp sudden jumps
  max_formality_swing: 0.15
  consistency_window_turns: 10
```

**Per turn (before LLM):**
```
proposed_warmth = expression.effective_warmth

allowed_warmth = clamp(
  proposed_warmth,
  session_tone_baseline - max_tone_drift_per_turn,
  session_tone_baseline + max_tone_drift_per_turn
)

# Exception: BDV.tone_shift = WARMER/SOFTER allows +0.08 extra (behavior authorized shift)
```

After output (post-turn): update `session_tone_baseline = EMA(effective_warmth, alpha=0.25)`.

**Personality consistency anchor:** merge `profile.traits` as floor — coherence cannot express warmth below `profile.traits.warmth - 0.2` unless BDV tone SOFTER (empathetic distance).

---

### 2. Cross-layer conflict resolver (expression tie-breaker)

When layers disagree on **how** (not **whether**) to express:

| Situation | Layers | Coherence resolution |
|-----------|--------|----------------------|
| Emotional peak | BDV: ACK_ONLY · Arc: E high · Personality: long empathy | **Unified:** one warm phrase ≤ BDV word cap — arc colors warmth, not length |
| Wind-down | BDV: MINIMAL · Arc: winding_down · Personality: casual long | **Unified:** cap at MINIMAL — arc softens tone only |
| High warmth profile | BDV: NONE questions · Personality: playful | **Unified:** playfulness in word choice, zero questions |
| CPS recovery turn | Arc: low trust · BDV: RESPOND · Personality: warm | **Unified:** warm but shorter — trust recovery = less flourish, not less warmth |

**Algorithm (deterministic):**

```
resolve_expression(bdv, expression, arc_hint, anchor):

  # Priority stack — expression only
  1. BDV.length + question_budget + partial_response  → HARD (never expand)
  2. BDV.tone_shift                                    → authorized shift band
  3. arc_hint (warmth, phase)                          → nuance within band
  4. personality traits                                → anchor floor/ceiling
  5. identity stability clamp                          → final smooth

  return VoiceDirective
```

No softmax. No new probabilities. **Merge rules only.**

---

### 3. Single voice constraint

Output must read as **one consciousness**, not stacked decisions.

```yaml
SingleVoiceConstraint:
  one_register_per_turn: true        # no formal opener + casual body
  one_emotional_posture: true        # not warm + clinical in same message
  no_layer_leakage: true             # never expose internal logic
  max_rhetorical_devices: 1          # no list + question + summary same turn
  ack_question_mutex: true           # ack turns: no trailing "?"

prompt_fragment_always:
  - "Respond as one person with one consistent voice this turn."
  - "Do not sound like a system explaining layers of reasoning."
```

**Post-generation check (lightweight):**
```
voice_coherence_score = f(register_consistency, length_within_directive, no_layer_leakage)

IF voice_coherence_score < 0.5:
  flag for policy.rewrite_with_tighter_voice_directive
  # NOT behavior re-decide
```

Distinct from **CPS** (chatbot anti-patterns) — coherence checks **identity unity**, CPS checks **chatbot habits**.

---

### 4. Controlled drift allowance (human imperfection)

**Paradox:** Semakin sempurna coherence, semakin kecil kemungkinan terasa hidup — kecuali ada **controlled looseness**.

Coherence binds identity — but humans are not perfectly coherent. Sistem perlu ruang untuk:

- slight tone mismatch (hangat tapi sedikit awkward — OK)
- minor asymmetry (jawab tidak simetris dengan input)
- conversational roughness (frasa tidak terlalu polished)

```yaml
ControlledDriftAllowance:
  enabled: true
  imperfection_budget: float       # 0.0–1.0 per session, regen +0.15/turn cap 1.0
  warmth_slack: 0.06               # extra beyond clamp when budget spent
  register_softness: 0.1           # allow micro register blend, not full violation
  skip_verify_threshold: 0.45      # voice_coherence 0.45–0.5 → pass with budget spend
  asymmetry_ok: true               # allow slightly shorter/longer than exact cap ±15%
```

**When to apply (deterministic):**

```
IF bdv.engagement >= 0.5 AND arc_hint.emotional_drift != 0:
  apply warmth_slack (+0.06 max) instead of hard clamp edge

IF execution_profile IN (presence, whisper) AND imperfection_budget > 0.3:
  allow asymmetry_ok on word count (±15%)
  spend 0.1 imperfection_budget

IF voice_coherence_score IN [0.45, 0.5) AND imperfection_budget > 0.2:
  pass verify_voice — do not trigger rewrite
  spend 0.15 budget
  log: controlled_drift_applied
```

**Rules:**

- Drift allowance **never** overrides BDV speak/length/question_budget
- Drift allowance **never** bypasses policy hard blocks
- Budget depletes — system gradually tightens again (prevents permanent sloppiness)
- `imperfection_budget` resets partially on session gap > 30 min

> **Design truth:** Perfect unity = synthetic. Controlled drift = human.

---

## Schemas

### Input

```yaml
CoherenceInput:
  bdv: BehaviorDirectiveVector
  expression: ExpressionConstraints      # from personality
  profile: PersonalityProfile
  arc_hint:
    relational_warmth: float
    arc_phase: string
    emotional_drift: float
  identity_anchor: IdentityAnchor        # session state
  execution_profile: ghost | whisper | standard | presence | focused
```

### Output — VoiceDirective (unified)

Single object consumed by LLM assembly. Replaces passing raw `expression` alone.

```yaml
VoiceDirective:
  # Frozen from BDV — coherence cannot mutate
  speak: copied from BDV
  question_budget: copied from BDV
  max_words: min(expression.max_words, bdv-implied cap)
  max_sentences: from BDV.length resolution

  # Merged expression
  effective_warmth: float              # after stability clamp
  voice_register: casual | neutral | warm
  empathy_mode: presence | neutral | informational
  tone_notes: string[]                  # merged prompt fragments

  # Single voice
  single_voice: SingleVoiceConstraint
  template_ack: string | null          # whisper path

  # Human imperfection (v1.1)
  drift_allowance_applied: bool
  imperfection_budget_after: float
```

---

## Pipeline placement

```
behavior.decide() → BDV
personality.apply() → ExpressionConstraints
coherence.bind() → VoiceDirective          ← NEW (pre-LLM)
policy.pre_check(BDV, ...)
llm.complete(VoiceDirective, memory, policy)
policy.post_check()
coherence.verify_voice(output, VoiceDirective)  ← NEW (light post-check)
behavior.feedback()
```

**Skipped when:** `execution_profile = ghost` (no generation).

**Whisper path:** coherence binds template_ack + single_voice only — no full merge.

---

## Module design (lightweight)

Not a heavy engine. One module, ~3 functions:

```
bind(input: CoherenceInput) → VoiceDirective
verify_voice(output: str, directive: VoiceDirective) → VoiceCoherenceResult
update_anchor(anchor, directive, output) → IdentityAnchor
```

Location: `src/persona_ai/coherence/`  
**Depends on:** `core` only.  
**Must NOT:** import behavior internals, llm, re-run OAL.

State: `IdentityAnchor` persisted in session (via session manager) — not arc, not memory facts.

---

## Examples

### Vent — layers align

```
BDV: ACK_ONLY, MINIMAL, WARMER, questions=NONE
Expression: empathy_mode=presence, max_words=20
Arc: drift=+0.2, phase=deepening

Coherence:
  conflict: personality wants presence, BDV wants minimal
  resolution: presence in word choice, minimal in length
  effective_warmth: 0.78 (baseline 0.65 + WARMER auth + arc)
  template_ack: "Berat ya."

VoiceDirective: one warm micro-phrase, no questions
```

### Tone drift prevented

```
Turn 5: effective_warmth=0.55
Turn 6: personality proposes 0.82 (spike)
BDV: tone_shift=STABLE

Coherence:
  clamp to 0.55 + 0.12 = 0.67 max
  adjustment: warmth_clamped
```

### Policy boundary (preview)

```
Coherence binds voice.
Policy blocks forbidden content.
Policy MUST NOT alter speak/silence — only rewrite/remove violations.

If policy and coherence conflict on wording:
  policy wins on content safety
  coherence preserves register in rewrite request
```

→ Detailed in CONVERSATION_POLICY.md (next doc).

---

## What coherence does NOT do

| ❌ | Owner |
|----|-------|
| Decide SILENCE vs RESPOND | Behavior |
| CQF / CPS scoring | Behavior |
| OAL arbitration | Behavior |
| Safety / PII / legal blocks | Policy |
| Store user facts | Memory |
| Store emotional trajectory | Arc |
| Generate text | LLM |

---

## Testing checklist

- [ ] BDV.question_budget unchanged after bind()
- [ ] warmth spike clamped when tone_shift=STABLE
- [ ] ACK + arc emotional peak → one phrase, not paragraph
- [ ] ghost profile skips bind()
- [ ] verify_voice flags register mismatch, does not call behavior.decide()
- [ ] Controlled drift spends budget on presence profile, not on ghost
- [ ] Drift never expands question_budget or speak action

---

## Related docs

| Doc | Relasi |
|-----|--------|
| [PERSONALITY.md](PERSONALITY.md) | Upstream expression draft |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Pipeline step |
| CONVERSATION_POLICY.md | Next — hard gate, not identity binding |
