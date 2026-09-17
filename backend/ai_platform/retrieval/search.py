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

from qdrant_client import models as qmodels

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


@dataclass(frozen=True)
class ChunkRecord:
    """Um chunk ja indexado, lido diretamente (sem busca por similaridade) — usado por
    domains/procurement/tenders/requirements_service.py (Fase 6) para varrer todos os chunks
    de uma DocumentVersion e aplicar a etapa de regra (filtro de cabecalho) antes de qualquer
    classificacao por IA."""

    chunk_index: int
    document_version_id: uuid.UUID
    section: str | None
    heading_path: list[str]
    chunk_type: str
    page_start: int
    page_end: int
    content: str


async def get_document_chunks(
    document_version_id: uuid.UUID, *, chunk_type: str | None = None
) -> list[ChunkRecord]:
    """Le (via scroll, sem vetor de busca) todos os chunks indexados de uma DocumentVersion,
    opcionalmente filtrados por `chunk_type`. Qdrant nao ordena resultado de scroll por
    relevancia (nao ha query aqui) — a ordem nao importa para o caso de uso atual (extracao de
    requisitos processa cada chunk candidato independentemente)."""
    client = get_qdrant_client()

    must: list[qmodels.Condition] = [
        qmodels.FieldCondition(
            key="document_version_id",
            match=qmodels.MatchValue(value=str(document_version_id)),
        )
    ]
    if chunk_type is not None:
        must.append(
            qmodels.FieldCondition(key="chunk_type", match=qmodels.MatchValue(value=chunk_type))
        )

    records: list[ChunkRecord] = []
    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=GLOBAL_KNOWLEDGE_COLLECTION,
            scroll_filter=qmodels.Filter(must=must),
            limit=100,
            offset=offset,
        )
        for point in points:
            assert point.payload is not None
            records.append(
                ChunkRecord(
                    chunk_index=point.payload["chunk_index"],
                    document_version_id=uuid.UUID(point.payload["document_version_id"]),
                    section=point.payload.get("section"),
                    heading_path=point.payload.get("heading_path", []),
                    chunk_type=point.payload["chunk_type"],
                    page_start=point.payload["page_start"],
                    page_end=point.payload["page_end"],
                    content=point.payload["content"],
                )
            )
        if offset is None:
            break

    return records


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
