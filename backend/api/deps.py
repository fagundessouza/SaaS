"""Dependencias compartilhadas da API.

NOTA DE ESCOPO (Fase 1): a extracao de tenant aqui usa um header `X-Tenant-Id` validado contra a
tabela `tenants`. Isso e um substituto deliberadamente simples para autenticacao real — a Fase 2
(Auth + Multi-tenancy + Subscription) substitui isso por sessao/JWT com usuario autenticado.
O contrato que importa desde ja (e que a Fase 2 preserva) e: toda rota tenant-scoped ativa
`tenant_scope(tenant_id)` a partir de uma fonte confiavel do lado do servidor, nunca aceitando
tenant_id livre em body/query.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Header, HTTPException

from core.db.session import system_session
from core.tenancy.context import tenant_scope
from core.tenancy.models import Tenant


async def require_tenant(
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
) -> AsyncIterator[UUID]:
    try:
        tenant_id = UUID(x_tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-Id invalido") from exc

    async with system_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant nao encontrado")

    with tenant_scope(tenant_id):
        yield tenant_id
