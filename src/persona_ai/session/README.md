# Session Manager

Lifecycle & context percakapan per user/persona/channel.

## Tanggung jawab

- Create / hydrate / terminate session
- Bind `user_id`, `persona_id`, `channel`
- Provide immutable `SessionContext` per turn
- Persist turn metadata

## Dependency

- **Depends on:** `core`
- **Used by:** `conversation`
