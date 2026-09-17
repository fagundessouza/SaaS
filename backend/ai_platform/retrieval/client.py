"""Cliente Qdrant compartilhado — Global Knowledge Layer (ver ADR-0005 e
docs/DATA_AND_KNOWLEDGE_ARCHITECTURE.md). Uma unica collection GLOBAL (sem tenant_id, edital
publicado e informacao publica); quando a Tenant Knowledge Layer existir (Fase 6+), sera uma
collection separada com filtro de tenant_id obrigatorio na assinatura da funcao de retrieval —
nunca opcional (mesmo padrao ja aplicado em core.storage/core.cache, ver ADR-0002).
"""

from __future__ import annotations

from qdrant_client import AsyncQdrantClient

from core.config import get_settings

GLOBAL_KNOWLEDGE_COLLECTION = "global_knowledge"

_client: AsyncQdrantClient | None = None


def get_qdrant_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(url=get_settings().qdrant_url)
    return _client
