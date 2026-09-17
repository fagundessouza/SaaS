"""Fixtures compartilhadas.

`pytest-asyncio` (modo auto) cria um event loop por funcao de teste por padrao. Os singletons de
engine/conexao em core.db.session, core.cache.redis_client e core.jobs.enqueue sao criados de
forma preguicosa e ficam presos ao event loop em que nasceram — reusa-los sob um loop novo
gera `RuntimeError: Event loop is closed`. Este fixture derruba os singletons apos cada teste
para que o proximo teste os recrie contra o loop corrente.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio

from core.cache import redis_client as redis_client_module
from core.db import session as db_session_module
from core.jobs import enqueue as enqueue_module


def unique_email(prefix: str = "user") -> str:
    """E-mail garantidamente unico entre execucoes de teste — necessario porque EmailIndex.email
    tem constraint de unicidade global (ver core/auth/models.py), e o Postgres de teste nao e
    limpo entre rodadas de `pytest` (mesma infra do docker-compose de desenvolvimento)."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}@exemplo.com"


def unique_cnpj() -> str:
    """14 digitos numericos garantidamente unicos entre execucoes de teste — mesma razao de
    `unique_email` (company_profiles.cnpj tambem e globalmente unico). Nao precisa ser um CNPJ
    com digito verificador valido, so nao pode colidir."""
    digits = uuid.uuid4().int
    return "".join(str((digits >> (i * 4)) % 10) for i in range(14))


@pytest_asyncio.fixture(autouse=True)
async def _reset_async_singletons() -> AsyncGenerator[None, None]:
    yield

    if db_session_module._engine is not None:
        await db_session_module._engine.dispose()
    db_session_module._engine = None
    db_session_module._session_factory = None

    if redis_client_module._redis is not None:
        await redis_client_module._redis.aclose()
    redis_client_module._redis = None

    if enqueue_module._pool is not None:
        await enqueue_module._pool.aclose()
    enqueue_module._pool = None
