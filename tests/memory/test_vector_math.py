from persona_ai.memory.local_embedder import local_embed_text
from persona_ai.memory.vector_math import cosine_similarity


def test_cosine_identical_high():
    a = local_embed_text("Ko suka musik reggae")
    b = local_embed_text("Ko suka musik reggae")
    assert cosine_similarity(a, b) > 0.99


def test_cosine_unrelated_lower():
    a = local_embed_text("Ko suka musik reggae")
    b = local_embed_text("Sa mo beli spare part mobil")
    assert cosine_similarity(a, b) < cosine_similarity(a, a) * 0.85
