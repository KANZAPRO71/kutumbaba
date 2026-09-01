# Memory Engine

Cross-session **facts, preferences, relational patterns** — not arc trajectory.

Spec: [docs/MEMORY.md](../../../docs/MEMORY.md)

## API

```
retrieve(user_id, query, scopes[]) → MemoryBundle + MemorySignals
commit(user_id, turn, candidates[]) → CommitResult   # async OK
forget(user_id, filter) → void
```

## Rules

- Never override BDV
- Soft bias to behavior pressure (cap 0.10)
- Do not store transient emotion, CPS/CQF, arc state

## Dependency

- **Depends on:** `core`
- **Used by:** `conversation`, `plugins`
