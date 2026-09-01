# LLM Adapter

Model-agnostic gateway ke Gemini, GPT, Claude, dll.

## Tanggung jawab

- `complete(LLMRequest) → LLMResponse`
- Provider implementations di subfolder `providers/`
- Swap model = ganti config + adapter class

## Struktur (rencana)

```
llm/
├── adapter.py       # interface
└── providers/
    ├── openai.py
    ├── gemini.py
    └── anthropic.py
```

## Dependency

- **Depends on:** `core` only
- **Used by:** `conversation`
