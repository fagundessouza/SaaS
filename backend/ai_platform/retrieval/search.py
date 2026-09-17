"""Busca semantica no Global Knowledge Layer.

Sem reranking aqui de proposito: reranking so entra no estagio de Analysis (Fase 8), nunca no
Radar/retrieval basico — decisao ja registrada na Fase 0 (ver
docs/00-CRITICAL_ANALYSIS.md, item 6 da tabela de ambiguidades, e
docs/SYSTEM_ARCHITECTURE.md).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from ai_platform.embeddings.fastembed_provider import get_embedding_provider
from ai_platform.retrieval.client import GLOBAL_KNOWLEDGE_COLLECTION, get_qdrant_client
from core.observability.metrics import knowledge_search_duration_seconds


@dataclass(frozen=True)
class SearchResult:
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    section: str | None
    heading_path: list[str]
    chunk_type: str
    page_start: int
    page_end: int
    content: str
    score: float


async def search_global_knowledge(query: str, *, limit: int = 5) -> list[SearchResult]:
    provider = get_embedding_provider()
    [query_vector] = await provider.embed([query])

    client = get_qdrant_client()

    started_at = time.monotonic()
    response = await client.query_points(
        collection_name=GLOBAL_KNOWLEDGE_COLLECTION,
        query=query_vector,
        limit=limit,
    )
    knowledge_search_duration_seconds.observe(time.monotonic() - started_at)

    return [
        SearchResult(
            document_id=uuid.UUID(point.payload["document_id"]),
            document_version_id=uuid.UUID(point.payload["document_version_id"]),
            section=point.payload.get("section"),
            heading_path=point.payload.get("heading_path", []),
            chunk_type=point.payload["chunk_type"],
            page_start=point.payload["page_start"],
            page_end=point.payload["page_end"],
            content=point.payload["content"],
            score=point.score,
        )
        for point in response.points
        if point.payload is not None
    ]
