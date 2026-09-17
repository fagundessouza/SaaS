"""Testa o provider de embeddings real (sem mock — fastembed roda localmente, sem rede apos o
primeiro download do modelo). Ver ai_platform/embeddings/fastembed_provider.py.
"""

from __future__ import annotations

import math

from ai_platform.embeddings.fastembed_provider import get_embedding_provider


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


async def test_embed_returns_vectors_with_configured_dimension() -> None:
    provider = get_embedding_provider()

    vectors = await provider.embed(["Edital de pregao eletronico", "Outro texto qualquer"])

    assert len(vectors) == 2
    assert all(len(v) == provider.dimension for v in vectors)


async def test_embed_ranks_semantically_related_text_higher() -> None:
    provider = get_embedding_provider()

    texts = [
        "Edital de Pregao Eletronico para aquisicao de material de escritorio",
        "Compra de canetas, papel e grampeadores para uso administrativo",
        "Contratacao de servicos de limpeza e conservacao predial",
    ]
    vectors = await provider.embed(texts)

    related = _cosine_similarity(vectors[0], vectors[1])
    unrelated = _cosine_similarity(vectors[0], vectors[2])

    assert related > unrelated
