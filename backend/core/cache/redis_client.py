"""Conexao Redis compartilhada. Usada tanto pelo cache (core.cache.client) quanto pelo
despacho de eventos (core.events.dispatcher) e pela fila de jobs (core.jobs) — mesma
infraestrutura, papeis logicos diferentes.
"""

from __future__ import annotations

from redis.asyncio import Redis

from core.config import get_settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis
