"""Fixtures compartilhadas.

`pytest-asyncio` (modo auto) cria um event loop por funcao de teste por padrao. Os singletons de
engine/conexao em core.db.session, core.cache.redis_client, core.jobs.enqueue e
ai_platform.retrieval.client sao criados de forma preguicosa e ficam presos ao event loop em que
nasceram — reusa-los sob um loop novo gera `RuntimeError: Event loop is closed`. Este fixture
derruba esses singletons apos cada teste para que o proximo teste os recrie contra o loop
corrente.

`ai_platform.embeddings.fastembed_provider._provider` e a UNICA excecao deliberada — o modelo
ONNX nao faz I/O assincrono (so `asyncio.to_thread` em cima de computo sincrono), entao nao fica
preso a nenhum event loop, e recarrega-lo a cada teste custaria ~15s por teste sem necessidade.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from ai_platform.retrieval import client as qdrant_client_module
from core.cache import redis_client as redis_client_module
from core.db import session as db_session_module
from core.jobs import enqueue as enqueue_module
from core.storage.client import get_storage_client


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


def unique_text(base: str) -> str:
    """Texto garantidamente unico entre chamadas — necessario para testes de
    ai_platform.documents (Document.content_hash e unico globalmente, ver ADR-0012). Gerar a
    partir de uma funcao chamada dentro de cada teste, nunca de uma constante de modulo
    compartilhada entre testes: dois testes que precisam de identidade de Document independente
    mas usam o mesmo texto fixo colidem no mesmo content_hash, mesmo dentro de uma unica
    execucao do pytest (sem rollback entre testes — ver _reset_async_singletons)."""
    return f"{base} [{uuid.uuid4().hex[:8]}]"


@pytest.fixture(scope="session", autouse=True)
def _ensure_storage_bucket() -> None:
    """Sem isto, testes que tocam storage (ex.: tests/integration/test_tender_ingestion.py)
    so passavam localmente porque uma API rodada manualmente antes ja tinha criado o bucket
    (ensure_bucket roda no lifespan de api/main.py, que os testes via ASGITransport nunca
    disparam). Garantido aqui uma vez por sessao de teste, independente de qualquer processo
    externo ter rodado antes."""
    get_storage_client().ensure_bucket()


@pytest.fixture(scope="session", autouse=True)
def _reset_knowledge_collection() -> None:
    """Mesma razao de `_ensure_storage_bucket`, mas para o Qdrant: sem isto, a colecao
    `global_knowledge` acumula chunks quase identicos de sessoes de `pytest` anteriores sem
    limite — ja causou um teste flaky em tests/integration/test_retrieval.py (`limit=20` na
    busca nao e imune a acumulo *indefinido* entre muitas execucoes de uma mesma sessao de
    desenvolvimento; achado apos 113 pontos acumulados). Recriada do zero uma vez por sessao de
    pytest; os poucos chunks que os proprios testes desta sessao inserem depois nao chegam perto
    de reproduzir o problema.

    Fixture sincrona (nao `pytest_asyncio`) de proposito: roda antes de qualquer event loop de
    teste existir, via `asyncio.run` isolado — e por isso reseta `_client` para `None` no final,
    para que o primeiro teste real recrie o client preso ao loop correto (mesmo motivo de
    `_reset_async_singletons` abaixo)."""

    async def _reset() -> None:
        client = qdrant_client_module.get_qdrant_client()
        if await client.collection_exists(qdrant_client_module.GLOBAL_KNOWLEDGE_COLLECTION):
            await client.delete_collection(qdrant_client_module.GLOBAL_KNOWLEDGE_COLLECTION)
        await client.close()

    asyncio.run(_reset())
    qdrant_client_module._client = None


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

    if qdrant_client_module._client is not None:
        await qdrant_client_module._client.close()
    qdrant_client_module._client = None
