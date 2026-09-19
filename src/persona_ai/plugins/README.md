# Plugin / Domain System

Extensibility tanpa fork core.

## Hook points

- `on_turn_start`
- `on_behavior_signals` — inject ke behavior engine
- `on_memory_retrieve`
- `on_llm_tools` — function calling
- `on_response_post`

## Implemented

- **device_context** — `get_location_snapshot`, `get_device_status` (Android Chaquopy → `DeviceContextBridge`)
- **web_search_live** — `search_live_web` (NON_BLOCKING)
- Arsitektur async: [LIVE_ASYNC_TOOLS.md](./LIVE_ASYNC_TOOLS.md)

## Contoh plugin (nanti)

- `healthcare-intake`
- `ecommerce-support`
- `language-tutor`

## Dependency

- **Depends on:** `core`
- **Must NOT import:** `conversation` (inverse dependency only)
- **Used by:** `conversation` via registry
