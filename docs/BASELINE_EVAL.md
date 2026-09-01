# North Star Baseline — Human Eval Protocol (FROZEN)

**Status:** Active experiment lock  
**Goal:** Prove Persona text governance moat before any voice, embed, or preset wiring changes.

---

## Decision lock

G1–G3 are **one job**: moat validation.

```
Human eval (50 paired judgments, Gemini live, blind)
        ↓
Preset / prompt fixes — only if evidence supports (post-baseline)
        ↓
Voice (Gemini Live transport — BDV before audio, never repair-after)
```

**Do not start Gemini Live until baseline completes.**

Interactions API (current text adapter) is the correct Google path for new projects — no adapter migration needed for this baseline.

---

## Frozen until baseline completes

Do **not** change:

| Area | Examples |
|------|----------|
| `presets/default_companion.json` | traits, lexicon, ack templates |
| Behavior thresholds | defer, vent, closure heuristics in `decide()` |
| Prompt wording | anything that shifts treatment output |
| Gemini model/config | `GEMINI_MODEL`, adapter options |
| Personality→decide coupling | preset behavior biases (G5) |
| Lexicon→renderer wiring | preset avoided phrases (G4) |

Changing these **before** baseline invalidates the control arm.

---

## Allowed during baseline (infrastructure only)

- Packaging / CLI scripts
- Test infrastructure
- Pre-LLM latency telemetry (`TurnTrace.timing`)
- Documentation
- Analysis / measurement tooling

---

## Experiment design

| Parameter | Value |
|-----------|-------|
| Scenarios | 10 fixed (`eval/scenarios.py`) |
| Reviewers | 5 per scenario |
| Total judgments | **50** paired (non-tie count toward win rates) |
| Control | `GeminiDirectClient` — same Gemini adapter, no Persona |
| Treatment | `PersonaEvalClient` — Persona + frozen `default_companion` preset |
| Model | Same `GEMINI_MODEL` for both arms (set once, record in metadata) |
| Blind | Reviewers never see "Persona" / "control" labels |

---

## Primary metric: Governance Win Rate

Count judgments **only when Persona governance materially differs** from control:

- `SILENCE`
- `DEFER`
- `ACK_ONLY`
- Or treatment skipped LLM while control called LLM

```
Governance Win Rate = Persona preferred / total non-tie judgments (governance differs only)
```

This tests the moat directly — timing + restraint, not generic chattiness.

Secondary: overall preference win rate across all 10 scenarios.

---

## Post-baseline decision tree

| Outcome | Action |
|---------|--------|
| **A** — Persona clearly wins | Fix G4/G5 from evidence → voice integration |
| **B** — Wins only on closure/vent/defer | Narrow Persona to timing + restraint engine |
| **C** — No lift | Fix thesis/behavior first — no voice, no memory |

---

## Operator workflow

### 1. Prepare frozen baseline artifacts

Requires `GEMINI_API_KEY` and optional `GEMINI_MODEL`:

```bash
pip install -e ".[gemini,dev]"
persona-baseline prepare
```

Writes:

| File | Purpose |
|------|---------|
| `.persona_ai/eval/baseline_metadata.json` | Frozen config snapshot (model, preset version, timestamp) |
| `.persona_ai/eval/ab_results.json` | Control + treatment outputs per scenario |
| `.persona_ai/eval/blind_pairs_manifest.json` | **Analyst only** — never share with reviewers |
| `.persona_ai/eval/reviewer_forms.json` | Blind forms for human raters |

### 2. Collect human scores

Share `reviewer_forms.json` only — **not** the manifest or results file.

Each reviewer submits scores via your chosen channel; analyst records into:

`.persona_ai/eval/human_scores.jsonl`

One JSON object per line:

```json
{
  "pair_id": "...",
  "scenario_id": "closure_after_long",
  "naturalness": 6,
  "timing": 7,
  "intrusiveness": 5,
  "emotional_fit": 6,
  "preference": "A",
  "reviewer_id": "r1"
}
```

Or use CLI:

```bash
persona-eval-record --pair-id ... --scenario-id ... --naturalness 6 --timing 7 \
  --intrusiveness 5 --emotional-fit 6 --preference A --reviewer-id r1
```

### 3. Check progress

```bash
persona-baseline status
```

Target: **50** judgments (`10 scenarios × 5 reviewers`).

### 4. Analyze (after 50 collected)

```bash
persona-eval-analysis --results .persona_ai/eval/ab_results.json \
  --scores .persona_ai/eval/human_scores.jsonl \
  --pairs .persona_ai/eval/blind_pairs_manifest.json
```

Send analysis JSON output to the project lead before any treatment tuning.

---

## Latency gate (parallel track)

ROADMAP v1 exit: pre-LLM p95 < 80 ms (excludes LLM).

After running scenarios, inspect `TurnTrace.timing.pre_llm_ms` via runtime tests or a batch latency script — do not optimize behavior until baseline human scores exist.

---

## Voice architecture (future — do not build yet)

```
Voice input → Behavior/Persona → BDV / VoiceDirective → Gemini Live stream → audio out
```

Never: Voice → Gemini direct → Persona repair-after.
