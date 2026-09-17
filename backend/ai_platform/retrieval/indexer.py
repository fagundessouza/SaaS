"""Indexa os chunks de uma DocumentVersion no Global Knowledge Layer (Qdrant). Idempotente por
`document_version_id` — mesma logica de dedup do Global Processing Cache (ADR-0005/ADR-0012),
so que aqui o "processamento caro" e chunking+embedding em vez de OCR.
"""

from __future__ import annotations

import time
import uuid

from qdrant_client import models as qmodels

from ai_platform.chunking.chunker import chunk_document
from ai_platform.documents.models import DocumentVersion
from ai_platform.embeddings.fastembed_provider import get_embedding_provider
from ai_platform.retrieval.client import GLOBAL_KNOWLEDGE_COLLECTION, get_qdrant_client
from core.db.session import system_session
from core.observability.logging import get_logger
from core.observability.metrics import (
    knowledge_chunks_indexed_total,
    knowledge_indexing_cache_hits_total,
    knowledge_indexing_duration_seconds,
)

logger = get_logger(__name__)


class DocumentVersionNotFoundError(Exception):
    pass


async def ensure_collection_exists() -> None:
    client = get_qdrant_client()
    provider = get_embedding_provider()
    if await client.collection_exists(GLOBAL_KNOWLEDGE_COLLECTION):
        return
    await client.create_collection(
        collection_name=GLOBAL_KNOWLEDGE_COLLECTION,
        vectors_config=qmodels.VectorParams(
            size=provider.dimension, distance=qmodels.Distance.COSINE
        ),
    )
    logger.info(
        "knowledge.collection_created",
        collection=GLOBAL_KNOWLEDGE_COLLECTION,
        dimension=provider.dimension,
    )


async def index_document_version(document_version_id: uuid.UUID, *, force: bool = False) -> int:
    client = get_qdrant_client()
    await ensure_collection_exists()

    if not force:
        existing = await client.count(
            collection_name=GLOBAL_KNOWLEDGE_COLLECTION,
            count_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="document_version_id",
                        match=qmodels.MatchValue(value=str(document_version_id)),
                    )
                ]
            ),
        )
        if existing.count > 0:
            knowledge_indexing_cache_hits_total.inc()
            logger.info("knowledge.index_cache_hit", document_version_id=str(document_version_id))
            return 0

    async with system_session() as session:
        version = await session.get(DocumentVersion, document_version_id)
        if version is None:
            raise DocumentVersionNotFoundError(str(document_version_id))
        page_texts = version.page_texts
        document_id = version.document_id

    started_at = time.monotonic()
    chunks = chunk_document(page_texts)
    if not chunks:
        logger.info("knowledge.no_chunks", document_version_id=str(document_version_id))
        return 0

    provider = get_embedding_provider()
    vectors = await provider.embed([chunk.content for chunk in chunks])

    points = [
        qmodels.PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "document_id": str(document_id),
                "document_version_id": str(document_version_id),
                "chunk_index": chunk.chunk_index,
                "section": chunk.section,
                "heading_path": chunk.heading_path,
                "chunk_type": chunk.chunk_type.value,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "content": chunk.content,
            },
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]

    await client.upsert(collection_name=GLOBAL_KNOWLEDGE_COLLECTION, points=points)

    duration = time.monotonic() - started_at
    knowledge_chunks_indexed_total.inc(len(points))
    knowledge_indexing_duration_seconds.observe(duration)
    logger.info(
        "knowledge.indexed",
        document_version_id=str(document_version_id),
        chunks=len(points),
        duration_s=round(duration, 2),
    )
    return len(points)
