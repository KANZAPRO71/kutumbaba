"""Optional Gemini embedding for higher-quality memory RAG (BYOK)."""

from __future__ import annotations

import logging
import os

from persona_ai.llm.gemini_models import gemini_embedding_model

_log = logging.getLogger(__name__)


def gemini_embed_text(text: str, *, api_key: str | None = None) -> list[float] | None:
    cleaned = " ".join((text or "").split()).strip()
    if len(cleaned) < 2:
        return None
    key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        return None
    try:
        from google import genai
    except ImportError:
        _log.debug("google-genai missing — gemini embed skipped")
        return None
    try:
        client = genai.Client(api_key=key)
        model = gemini_embedding_model()
        response = client.models.embed_content(
            model=model,
            contents=cleaned,
        )
        embeddings = getattr(response, "embeddings", None) or []
        if not embeddings:
            return None
        values = getattr(embeddings[0], "values", None)
        if not values:
            return None
        return [float(v) for v in values]
    except Exception:
        _log.debug("gemini embed failed", exc_info=True)
        return None
