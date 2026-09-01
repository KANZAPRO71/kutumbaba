# Conversation Policy Engine

**Hard gate only** — safety, forbidden content, compliance.

Spec: [docs/CONVERSATION_POLICY.md](../../../docs/CONVERSATION_POLICY.md)

## API

```
get_tier0_signals(context, input) → PolicySignal[]
pre_check(input, bdv, memory, context) → PolicyConstraints
post_check(draft, constraints, voice_directive) → PolicyResult
```

## Rules

- Never re-decide speak/silence
- Never adjust tone or feel
- Max 1 rewrite, then block/fallback

## Dependency

- **Depends on:** `core`
- **Used by:** `conversation`
