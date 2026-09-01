# Conversation Engine

**Orchestrator only** — linear pipeline, no intelligence.

Flow: [ARCHITECTURE.md](../../../docs/ARCHITECTURE.md) § Runtime flow

```
handle_turn(TurnRequest) → TurnResult
```

## Dependency

- **Depends on:** all engines via DI
- **Must NOT contain:** pressure, CQF, CPS, arc decay, prompt logic
