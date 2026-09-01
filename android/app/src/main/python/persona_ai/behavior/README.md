# Behavior Engine ★

Decision runtime — outputs **BehaviorDirectiveVector** (BDV).

Spec: [BEHAVIOR_ENGINE.md v1.3](../../../docs/BEHAVIOR_ENGINE.md)  
Architecture: [ARCHITECTURE.md](../../../docs/ARCHITECTURE.md)

## API

```
decide(input, arc) → BDV
feedback(output, bdv, arc) → QualitySnapshot + updated arc
```

## Internal packages (do not leak outside)

```
behavior/
├── interpret/
├── pressure/
├── inertia/
├── arbitration/    # OAL + stability
├── quality/        # CQF + CPS
└── engine.py
```

## Dependency

- **Depends on:** `core`, `arc`
- **Must NOT import:** `llm`, `memory`
- **Used by:** `conversation`
