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
import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ai_platform.retrieval import client as qdrant_client_module
from core.cache import redis_client as redis_client_module
from core.config import get_settings
from core.db import session as db_session_module
from core.events.dispatcher import STREAM_NAME
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


@pytest.fixture(scope="session", autouse=True)
def _reset_accumulating_tables() -> None:
    """Mesma razao de `_reset_knowledge_collection`, agora para o Postgres: como nenhuma tabela
    e limpa entre execucoes de `pytest` neste ambiente de dev, jobs que varrem a base inteira
    (ex.: `run_opportunity_matching_job`, O(tenants x tenders) — ver
    domains/procurement/opportunities/jobs.py) ficam cada vez mais lentos e eventualmente
    flaky/lentos o bastante para timeout, conforme a sessao de desenvolvimento acumula
    tenants/tenders de testes anteriores. Achado na Fase 8, depois de um dia inteiro de testes
    acumular milhares de linhas e `test_opportunity_matching_job.py` comecar a falhar de forma
    inconsistente (testes diferentes falhando a cada rodada — assinatura classica de lentidao
    por volume, nao de bug logico).

    `TRUNCATE ... CASCADE` em `tenants` e `tenders` (as duas raizes de acumulo — toda tabela
    TENANT pendura de `tenants` via FK, toda tabela de conteudo de edital pendura de `tenders`)
    limpa a arvore inteira de uma vez, uma unica vez por sessao de pytest. `documents`/
    `document_versions` (Document Intelligence, Fase 4) nao sao tocados — nao sao dependentes de
    `tenders` no grafo de FK (so referenciados por ele), e sozinhos nao causam a explosao
    combinatoria que motivou este fixture.

    `domain_events` (outbox, Fase 1) truncado separadamente: `DomainEvent.tenant_id` NAO tem FK
    (ver core/events/models.py — e infraestrutura interna despachada por um worker de confianca,
    nunca RLS-scoped), entao nao e alcancado pelo CASCADE acima. Achado na Fase 10, testando
    manualmente o Notification Engine antes de escrever os testes formais: 3801 eventos nao
    despachados tinham se acumulado ao longo do dia (todo evento publicado por qualquer teste
    desde a Fase 1 que nunca chamou `dispatch_pending_events`), fazendo o consumidor do stream
    processar um backlog gigante antes de alcancar o evento que o teste de fato criou.

    Roda via engine separada com `MIGRATIONS_DATABASE_URL` (usuario `licitacoes`, superusuario)
    porque `app_runtime` (usado por `tenant_session`/`system_session`) tem GRANT de
    SELECT/INSERT/UPDATE/DELETE mas nao de TRUNCATE (ver ops/docker/initdb/01-app-role.sql) —
    mesma engine que as migrations usam, ver alembic/env.py."""

    async def _reset() -> None:
        # `Settings` (pydantic-settings) le .env por conta propria, sem popular os.environ —
        # `load_dotenv()` e o que faz `MIGRATIONS_DATABASE_URL` aparecer aqui, mesmo padrao de
        # alembic/env.py (unico outro lugar que precisa do papel superusuario `licitacoes`).
        load_dotenv()
        url = os.environ.get("MIGRATIONS_DATABASE_URL") or get_settings().database_url
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE tenants, tenders CASCADE"))
            await conn.execute(text("TRUNCATE TABLE domain_events"))
        await engine.dispose()

        # O Redis Stream ja recebeu (XADD) todo evento despachado antes de hoje, e um consumer
        # group novo (Fase 10, ver domains/notifications/consumer.py) comeca do inicio do stream
        # (`id="0"`) — sem isto, o primeiro teste do Notification Engine teria que processar o
        # mesmo backlog gigante antes de chegar no evento que o proprio teste criou. `DELETE` na
        # chave remove o stream inteiro (consumer groups juntos); recriado com `mkstream=True`
        # na proxima chamada.
        redis = redis_client_module.get_redis()
        await redis.delete(STREAM_NAME)
        await redis.aclose()

    asyncio.run(_reset())
    # `get_redis()` acima criou o singleton preso ao loop temporario do `asyncio.run` desta
    # fixture (mesmo motivo de `qdrant_client_module._client = None` abaixo) — resetado para
    # `None` para que o primeiro teste real recrie o client contra o loop corrente.
    redis_client_module._redis = None


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
