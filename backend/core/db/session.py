"""Fabrica de engine/sessao assincrona do SQLAlchemy, com aplicacao de RLS por tenant.

Duas formas de obter sessao:
- tenant_session(): para toda operacao sobre dado TENANT. Aplica `SET LOCAL app.tenant_id` a
  partir do contexto ativo (core.tenancy.context) antes de qualquer query — e o que faz o
  Postgres aplicar as politicas de RLS definidas nas migrations. Falha se nao houver tenant ativo.
- system_session(): para operacao sobre dado GLOBAL (ex.: criar um Tenant). Nunca usar para ler
  ou escrever dado TENANT.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings
from core.tenancy.context import get_current_tenant_id

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def tenant_session() -> AsyncIterator[AsyncSession]:
    tenant_id = get_current_tenant_id()
    factory = get_session_factory()
    async with factory() as session, session.begin():
        # SET LOCAL nao aceita parametros bind ($1) no protocolo do Postgres — o valor precisa
        # ser literal na string. Isso e seguro aqui porque tenant_id e sempre um uuid.UUID ja
        # validado (nunca uma string crua vinda do cliente), entao str(tenant_id) so pode conter
        # digitos hexadecimais e hifens.
        await session.execute(text(f"SET LOCAL app.tenant_id = '{tenant_id}'"))
        yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session, session.begin():
        yield session
