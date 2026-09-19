"""Deterministic local text vectors — offline RAG without regex keyword lists."""

from __future__ import annotations

import hashlib

from persona_ai.memory.vector_math import normalize

_DEFAULT_DIMS = 96


def local_embed_text(text: str, *, dims: int = _DEFAULT_DIMS) -> list[float]:
    """Character trigram hashing — fast, on-device, no API."""
    cleaned = " ".join((text or "").split()).lower()
    vec = [0.0] * dims
    if len(cleaned) < 2:
        return vec
    padded = f"^{cleaned}$"
    for i in range(len(padded) - 2):
        gram = padded[i : i + 3]
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[bucket] += sign
    return normalize(vec)
