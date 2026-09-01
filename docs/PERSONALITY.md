# Personality Engine — Specification v1

**Status:** Draft v1.0  
**Terakhir diperbarui:** 2026-08-26  
**Referensi:** [BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md) (BDV) · [ARCHITECTURE.md](ARCHITECTURE.md) (execution profiles)

---

## One line

Personality Engine menjawab **"bagaimana ini terdengar?"** — bukan *"apakah harus bicara?"* (behavior) atau *"apa yang boleh?"* (policy).

> Teman yang paham konteks **terdengar** hangat, singkat saat perlu, dan tidak seperti customer service — tanpa mengubah keputusan BDV.

---

## Boundary (non-negotiable)

| Layer | Question | Can override BDV? |
|-------|----------|-------------------|
| Behavior | Kapan / apakah bicara? | — |
| **Personality** | **Bagaimana suara bicara?** | **Never** |
| Policy | Apa yang forbidden? | Hard block only |
| LLM | Isi teks apa? | Under constraints |

Personality **translates** BDV + profile → `ExpressionConstraints`. It does not change `speak`, `length`, or `question_budget`.

---

## Position in runtime

```
BDV (from behavior)
    │
    ├─ profile: ghost / whisper → personality BYPASS (ARCHITECTURE adaptive pipeline)
    │
    └─ profile: standard / presence / focused
           │
           ▼
    personality.apply(profile, bdv, arc_hint?) → ExpressionConstraints
           │
           ▼
    coherence.bind(bdv, expression, arc, anchor) → VoiceDirective
           │
           ▼
    LLMRequest.voice
```

**Arc hint (optional, read-only):** `relational_warmth`, `arc_phase` — bias expression intensity, not behavior.

---

## PersonalityProfile schema

Stable character — configured per persona, not per turn.

```yaml
PersonalityProfile:
  id: string
  name: string

  traits:                          # 0.0–1.0
    warmth: float                  # dingin ↔ hangat
    formality: float               # santai ↔ formal
    humor: float                   # serius ↔ playful
    directness: float              # indirect ↔ to the point
    empathy: float                 # transactional ↔ emotionally present

  voice:
    register: casual | neutral | warm
    sentence_length_bias: short | mixed | long
    emoji_policy: never | rare | match_user

  lexicon:
    preferred_phrases: string[]    # e.g. "yah", "oh iya"
    avoided_phrases: string[]        # assistant-isms

  bounds:                          # clamp expression, not BDV
    max_exclamation_per_turn: 1
    never_say: string[]              # merged with policy
```

Traits are **slow** — consistent across session. BDV `tone_shift` is **fast** — situational overlay.

---

## BDV → Expression mapping

### Input

```yaml
PersonalityInput:
  profile: PersonalityProfile
  bdv: BehaviorDirectiveVector
  arc_hint:                      # optional
    relational_warmth: float
    arc_phase: opening | exploration | deepening | resolution | winding_down
  execution_profile: whisper | standard | presence | focused
```

### Output — ExpressionConstraints

```yaml
ExpressionConstraints:
  # Compiled for LLM / template layer — not user-facing
  voice_register: casual | neutral | warm
  target_length: micro | short | medium | long    # mapped from BDV.length
  max_sentences: int
  max_words: int
  question_budget: int                            # copied from BDV — do not increase
  tone:
    base: from profile traits
    shift: STABLE | WARMER | SOFTER | MATCH_USER  # from BDV
    effective_warmth: float                        # computed
  empathy_mode: presence | neutral | informational
  humor_allowed: bool
  partial_ok: bool                                # from BDV.partial_response
  stop_after_answer: bool                         # from BDV.stop_rule = ONE_TURN
  delay_ms: int                                   # passthrough BDV.timing
  prompt_fragments: string[]                      # ordered constraint lines for LLM
  template_ack: string | null                     # whisper profile fallback
```

---

## Mapping rules (v1)

### 1. Length — BDV drives, personality shapes

| BDV.length | target_length | max_sentences | max_words |
|------------|---------------|---------------|-----------|
| MINIMAL | micro / short | 1 | 15–25 |
| NORMAL | medium | 2–3 | 60–80 |
| EXPAND | long | 4–6 | 150–200 |

Apply `profile.sentence_length_bias`: short profile → subtract 20% word cap.

If `bdv.partial_response` → cap at 1 sentence regardless.

### 2. Tone shift — situational overlay on traits

```
effective_warmth = clamp(
  profile.traits.warmth
+ shift_delta(bdv.tone_shift)
+ arc_hint.relational_warmth * 0.15   # subtle — arc already influenced BDV
, 0, 1)

shift_delta:
  STABLE: 0
  WARMER: +0.15
  SOFTER: +0.10 (warmth) + reduce directness cap
  MATCH_USER: inherit from last user message sentiment (light heuristic v1)
```

| effective_warmth | voice_register | empathy_mode |
|------------------|----------------|--------------|
| < 0.35 | neutral | informational |
| 0.35–0.65 | neutral / casual | neutral |
| > 0.65 | warm | presence |

### 3. Engagement level — expression intensity

| BDV.engagement_level | Personality mode |
|----------------------|------------------|
| < 0.35 | Minimal presence — short clauses, no flourish |
| 0.35–0.65 | Standard friend voice |
| > 0.65 | Full presence — allow subtle backchannel style openers ("Hmm,") if BACKCHANNEL_OK |

**presence execution profile:** force empathy_mode = presence, allow +1 sentence if BDV allows NORMAL length.

### 4. Questions — copy BDV, never expand

```
question_budget = bdv.question_budget   # NEVER profile-driven increase

IF bdv.questions = NONE:
  prompt_fragments += "Do not ask questions."

IF bdv.questions = CLARIFY_ONLY:
  prompt_fragments += "At most one clarifying question if truly ambiguous."
```

### 5. ACK_ONLY / whisper profile

When `execution_profile = whisper`:

- Prefer **template_ack** from personality if defined for vent/ack context
- Else micro-LLM with `max_words: 12`, `empathy_mode: presence`
- **Bypass** full trait elaboration — one human phrase

Example templates (persona-configurable):

| Context | Template pattern |
|---------|------------------|
| Vent | "{preferred_ack_vent}" → "Berat ya." |
| Neutral ack | "Oke." / "Iya." |
| Warm ack | "Iyaa, paham." |

---

## Friend voice vs assistant voice

Personality enforces **anti-assistant expression** at generation constraint level (complements CPS behavior-side).

| Assistant tone (avoid) | Friend tone (target) |
|------------------------|----------------------|
| "Tentu, saya akan bantu..." | Direct answer or ack |
| "Apakah ada hal lain?" | (silence — behavior, not personality) |
| "Berikut beberapa opsi:" | Only if BDV + user asked |
| "Sebagai teman virtual..." | Never |
| Over-structured bullets | Prose or single line when MINIMAL |

**prompt_fragments** always include:
```
Speak like a friend in conversation, not a customer service agent.
Match the energy of the message — do not over-explain.
```

---

## Meaningful silence (personality role)

On **ghost** profile (SILENCE/DEFER): personality **does not run**.

Silence is behavioral — personality has nothing to express. Optional channel UI ("listening") is outside this module.

When **SILENCE_EMPATHETIC** was considered but BDV chose ACK_ONLY instead: personality applies **presence** empathy in ≤1 sentence — not explanation.

---

## Arc phase → expression nuance (read-only)

Arc does not decide; personality adds **light** contextual coloring:

| arc_phase | Expression nuance |
|-----------|-------------------|
| opening | Slightly neutral — don't over-familiarize |
| exploration | Curious but not interrogative |
| deepening | More warmth if profile allows |
| resolution | Clear, grounded — no new threads |
| winding_down | Shorter, softer — match BDV partial/stop |

---

## Examples

### Vent — ACK_ONLY, WARMER, MINIMAL

```
BDV: speak=ACK_ONLY, length=MINIMAL, tone_shift=WARMER, questions=NONE
Profile: warmth=0.7, register=casual

ExpressionConstraints:
  target_length: short
  max_words: 18
  empathy_mode: presence
  effective_warmth: 0.85
  prompt_fragments:
    - "One short acknowledging phrase."
    - "Do not ask questions."
    - "Do not offer advice unless asked."
  template_ack: "Berat ya."
```

### Direct question — RESPOND, NORMAL

```
BDV: speak=RESPOND, length=NORMAL, questions=CLARIFY_ONLY, engagement=0.55
Profile: directness=0.6, formality=0.3

ExpressionConstraints:
  target_length: medium
  max_sentences: 3
  empathy_mode: neutral
  voice_register: casual
  prompt_fragments:
    - "Answer directly first."
    - "At most one clarifying question if needed."
```

### High engagement — presence profile

```
BDV: engagement=0.72, tone_shift=WARMER, arc_phase=deepening
Profile: empathy=0.8

→ empathy_mode: presence
→ effective_warmth boosted
→ allow conversational opener if BACKCHANNEL_OK
→ still bound by question_budget and max_words
```

---

## API

```
get_profile(persona_id) → PersonalityProfile
apply(profile, bdv, arc_hint?, execution_profile) → ExpressionConstraints
```

**whisper bypass:** if `execution_profile = whisper`, `apply()` may return minimal `ExpressionConstraints` + `template_ack` only.

---

## Dependency

- **Depends on:** `core` only
- **Must NOT import:** `llm`, `behavior` (receives BDV as data)
- **Used by:** `conversation` (step 7, when profile ≠ ghost/whisper-bypass)

---

## Testing checklist

- [ ] BDV `questions=NONE` → ExpressionConstraints never increases question_budget
- [ ] MINIMAL + partial_response → max 1 sentence enforced
- [ ] whisper profile → template or ≤12 words
- [ ] WARMER shift increases effective_warmth, does not change speak action
- [ ] ghost profile → personality not invoked
- [ ] avoided_phrases + policy never_say merged in prompt_fragments

---

## Related docs

| Doc | Relasi |
|-----|--------|
| [BEHAVIOR_ENGINE.md](BEHAVIOR_ENGINE.md) | BDV source |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Execution profiles, pipeline |
| CONVERSATION_POLICY.md | Hard blocks (TBD) |
