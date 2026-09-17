"""Cache Redis com chave sempre prefixada por tenant (ver ADR-0002 / docs/SECURITY_MODEL.md).

Nao existe metodo de cache "sem tenant" aqui de proposito: dado GLOBAL cacheavel (ex.: catalogo
de planos) e responsabilidade do modulo que o possui decidir se cabe em L1 (memoria de processo)
em vez de Redis — este cliente e para dado de tenant (L2, ver DATA_AND_KNOWLEDGE_ARCHITECTURE.md).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from core.cache.redis_client import get_redis

_NAMESPACE = "tenant-cache"


def _tenant_key(tenant_id: uuid.UUID, key: str) -> str:
    return f"{_NAMESPACE}:{tenant_id}:{key}"


async def cache_set(tenant_id: uuid.UUID, key: str, value: Any, ttl_seconds: int) -> None:
    redis = get_redis()
    await redis.set(_tenant_key(tenant_id, key), json.dumps(value), ex=ttl_seconds)


async def cache_get(tenant_id: uuid.UUID, key: str) -> Any | None:
    redis = get_redis()
    raw = await redis.get(_tenant_key(tenant_id, key))
    if raw is None:
        return None
    return json.loads(raw)


async def cache_delete(tenant_id: uuid.UUID, key: str) -> None:
    redis = get_redis()
    await redis.delete(_tenant_key(tenant_id, key))
