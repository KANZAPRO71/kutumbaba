# Coherence Layer

Identity glue — binds BDV + personality + arc into **one VoiceDirective**.

Spec: [docs/COHERENCE.md](../../../docs/COHERENCE.md)

## API

```
bind(CoherenceInput) → VoiceDirective
verify_voice(output, directive) → VoiceCoherenceResult
update_anchor(anchor, directive, output) → IdentityAnchor
```

## Rules

- Never change BDV `speak` or `question_budget`
- Not a second behavior engine; not policy

## Dependency

- **Depends on:** `core`
- **Must NOT import:** `behavior` (internals), `llm`
- **Used by:** `conversation` (between personality and LLM)
