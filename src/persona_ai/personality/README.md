# Personality Engine

**How it sounds** — not when to speak.

Spec: [docs/PERSONALITY.md](../../../docs/PERSONALITY.md)

## API

```
get_profile(persona_id) → PersonalityProfile
apply(profile, bdv, arc_hint?, execution_profile) → ExpressionConstraints
```

## Rules

- Never override BDV
- Bypass on `ghost` / `whisper` execution profiles (see ARCHITECTURE.md)

## Dependency

- **Depends on:** `core`
- **Must NOT import:** `llm`, `behavior`
- **Used by:** `conversation`
