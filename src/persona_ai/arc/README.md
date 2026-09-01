# Arc Engine

Conversation **trajectory** state — phase, warmth, trust, drift, threads.

**Not** user facts (→ `memory/`).  
**Not** decisions (→ `behavior/`).

Spec: [BEHAVIOR_ENGINE.md §8 & §8.6](../../../docs/BEHAVIOR_ENGINE.md)

## API

```
load(session_id) → ConversationArc
save(session_id, arc) → void
apply_decay(arc) → ConversationArc
```

## Dependency

- **Depends on:** `core`
- **Used by:** `behavior` (decide + feedback)
