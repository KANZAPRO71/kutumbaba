"""Client-visible memory RAG settings (env-driven)."""

from __future__ import annotations

from typing import Any

from persona_ai.llm.gemini_models import gemini_embedding_model
from persona_ai.memory.embedding_index import use_gemini_embeddings
from persona_ai.memory.gatekeeper import min_rag_score, rag_enabled
from persona_ai.memory.retrieve import MIN_QUERY_LEN_FOR_RAG


def memory_rag_client_config() -> dict[str, Any]:
    from persona_ai.conversation.companion_prefs import load_companion_prefs

    prefs = load_companion_prefs()
    gemini = use_gemini_embeddings()
    return {
        "enabled": rag_enabled(),
        "min_score": min_rag_score(),
        "min_query_chars": MIN_QUERY_LEN_FOR_RAG,
        "embedder": "gemini" if gemini else "local_trigram",
        "embedding_model": gemini_embedding_model() if gemini else None,
        "user_prefs": {
            "rag_enabled": prefs.rag_enabled,
            "rag_min_score": prefs.rag_min_score,
            "rag_use_gemini": prefs.rag_use_gemini,
        },
    }
