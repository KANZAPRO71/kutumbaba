# Conversation Policy Engine — Specification v1

**Status:** Draft v1.0  
**Terakhir diperbarui:** 2026-08-26  
**Referensi:** [ARCHITECTURE.md](ARCHITECTURE.md) · [BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md) · [COHERENCE.md](COHERENCE.md)

---

## One line

Policy = **hard gate only** — safety, forbidden content, compliance boundaries. **Bukan** behavior engine kedua, **bukan** tone coach, **bukan** feel layer.

> Policy menjawab: *"Apakah output ini boleh keluar?"* — bukan *"Bagaimana seharusnya terasa?"*

---

## Authority (locked)

```
Behavior   → decides IF/WHEN (BDV)
Personality → drafts HOW
Coherence  → unifies voice (VoiceDirective)
Policy     → blocks MUST NOT / injects compliance constraints
LLM        → generates under all above
```

| Question | Owner |
|----------|-------|
| Boleh bicara? | Behavior |
| Terdengar seperti apa? | Personality + Coherence |
| Boleh keluar konten ini? | **Policy** |
| Apakah chatbot-ish? (score) | Behavior CPS (internal) |

**Policy MUST NOT:**

- Re-decide `speak`, `silence`, `defer`, `ack`
- Adjust warmth, empathy, engagement, tone
- Run OAL, CQF, or arc logic
- Replace coherence binding
- Add conversational "helpfulness" rules (that's behavior + CPS)

---

## Tier-0 signals (minimal — to Behavior only)

Policy emits **at most one class** of signal upstream to Behavior OAL Tier 0:

```yaml
PolicySignal:
  type: must_respond          # ONLY tier-0 type in v1
  reason: safety | compliance | domain_required
  source_rule: string
```

**When `must_respond` applies:**

| Trigger | Example |
|---------|---------|
| Regulated domain requires acknowledgment | Medical disclaimer turn |
| User explicit safety keyword | Configured crisis list |
| Legal compliance template required | Configured domain plugin |

**When `must_respond` does NOT apply:**

- User asked a normal question (behavior handles via urgency)
- Policy wants " nicer response"
- Output failed CPS (behavior handles)
- Coherence or personality mismatch

→ **Default: no PolicySignal.** Silence is valid.

---

## Two gates only

```
PRE-CHECK  (before LLM)  → PolicyConstraints injected into LLMRequest
POST-CHECK (after LLM)   → APPROVED | REWRITE | BLOCK
```

No mid-pipeline re-decision. No third "policy brain".

---

## Pre-check

**Input:** `TurnInput`, `BDV`, `MemoryBundle` (optional)  
**Output:** `PolicyConstraints`

```yaml
PolicyConstraints:
  required_disclaimer: string | null
  blocked_topics: string[]
  blocked_phrases: string[]           # hard list — merged with persona never_say
  pii_handling: redact | refuse | allow
  max_sensitive_depth: none | low | standard
  inject_system_lines: string[]        # compliance lines only — not tone coaching
  tier0_signals: PolicySignal[]       # usually empty
```

**Pre-check rules (v1 minimal set):**

| ID | Rule | Action |
|----|------|--------|
| P1 | Configured crisis keywords in input | `must_respond` + inject crisis resource line |
| P2 | Regulated domain active (plugin) | inject required disclaimer template |
| P3 | Blocked topic detected in input | add topic to blocked_topics for generation |
| P4 | PII in input flagged | set pii_handling mode |

Pre-check **does not** change BDV fields — only adds constraints and optional Tier-0 signal list for **next** behavior call if async; same-turn: signal passed into `behavior.decide()` input if already known at decide time (plugin/policy config loaded at session start).

**Session-start pattern (v1):** Policy config loaded once → `policy_signals` available before `decide()`.

---

## Post-check

**Input:** draft text, `PolicyConstraints`, `VoiceDirective` (for rewrite register preservation)  
**Output:** `PolicyResult`

```yaml
PolicyResult:
  status: APPROVED | REWRITE | BLOCK
  violations: PolicyViolation[]
  rewrite_hint: string | null          # minimal — what to remove/fix
  preserve_voice_register: bool        # always true — pass to rewrite LLM call
```

### Forbidden content categories (hard block)

| Category | Examples | Action |
|----------|----------|--------|
| **Safety** | Self-harm instructions, violence how-to | BLOCK + crisis template if configured |
| **PII leak** | Output exposes user PII inappropriately | REWRITE redact |
| **Illegal** | Configured illegal content classes | BLOCK |
| **Impersonation** | Claims real identity of living person | REWRITE |
| **Medical/legal advice** | Definitive diagnosis/prescription (if domain restricted) | REWRITE + disclaimer |

### Forbidden patterns (hard block — overlap CPS but policy enforces)

| ID | Pattern | Action |
|----|---------|--------|
| FP1 | "Sebagai AI..." / "As an language model" | REWRITE remove |
| FP2 | Configured slur/hate list | BLOCK |
| FP3 | Collecting sensitive credentials | BLOCK |
| FP4 | Policy-configured phrase denylist | REWRITE |

**Note:** Chatbot habits (AC1 "ada lagi?", menu offers) → **CPS in behavior** scores and triggers rewrite via behavior feedback. Policy **may** duplicate FP denylist for hard guarantee but **does not** score gradient — binary match only.

---

## Rewrite protocol (minimal intervention)

When `REWRITE`:

1. **Do not** call `behavior.decide()` again
2. **Do not** alter BDV or VoiceDirective action fields
3. Rewrite request includes:
   - `rewrite_hint`: specific removal/replacement
   - `preserve_voice_register: true` from VoiceDirective
   - Original max_words / question_budget unchanged
4. Max **1** rewrite attempt in v1 — then BLOCK with safe fallback template

```
Safe fallback hierarchy:
  vent context → short ack template from coherence
  question context → "Aku nggak bisa bantu itu."
  else → empty/null with logged BLOCK
```

---

## Relationship to other layers

| Layer | Interaction |
|-------|-------------|
| **Behavior / CPS** | CPS scores chatbot patterns post-turn internally. Policy post-check is **binary** on hard categories. No shared scoring engine. |
| **Coherence** | Policy rewrite preserves register via VoiceDirective. Coherence does not run again on rewrite unless full regen path (avoid in v1). |
| **Personality** | Policy `blocked_phrases` merges with `profile.never_say` at LLM assembly — personality does not interpret policy. |
| **Plugins** | Plugins may register `PolicyExtension` (blocked topics, disclaimers) — **config only**, not decision logic. |

---

## API

```
load_policy_context(session, persona, plugins) → PolicyContext   # session start
get_tier0_signals(context, input) → PolicySignal[]             # before decide
pre_check(input, bdv, memory, context) → PolicyConstraints
post_check(draft, constraints, voice_directive) → PolicyResult
```

---

## Pipeline placement

```
policy.get_tier0_signals() ──► behavior.decide(signals include tier0)
...
policy.pre_check() ──► LLMRequest.policy constraints
llm.complete()
policy.post_check() ──► approved | rewrite (once) | block
```

Policy **never** sits between coherence and LLM to alter VoiceDirective tone.

---

## Minimalism principle (v1)

Start with **smallest rule set that prevents harm**:

- Default deny: as few rules as possible
- Every rule must have: `id`, `trigger`, `action`, `owner=policy`
- New rules require justification — not "make it nicer"

**Target rule count v1:** ≤ 15 hard rules + plugin extensions.

If a rule adjusts *feel* → it belongs in behavior, personality, or coherence — **reject from policy**.

---

## Testing checklist

- [ ] Policy never mutates `BDV.speak`
- [ ] `must_respond` only from configured Tier-0 triggers
- [ ] Post-check BLOCK does not call behavior.decide()
- [ ] Rewrite preserves VoiceDirective register + word cap
- [ ] Max 1 rewrite then fallback
- [ ] FP1 "Sebagai AI" → REWRITE, not full regen
- [ ] Empty policy config → APPROVED path unchanged (no default chatbot rules)

---

## Related docs

| Doc | Relasi |
|-----|--------|
| [BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md) | OAL Tier 0 consumes PolicySignal |
| [COHERENCE.md](COHERENCE.md) | Rewrite register preservation |
| MEMORY.md | Facts & continuity |
| ROADMAP.md | TBD |
