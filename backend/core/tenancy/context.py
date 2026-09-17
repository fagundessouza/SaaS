"""Contexto de tenant corrente da requisicao/job em execucao.

Este e o unico lugar do sistema onde "qual tenant esta ativo agora" e definido.
Nenhuma outra camada (storage, cache, retrieval, jobs) deve receber tenant_id por um caminho
diferente deste modulo — ver docs/SECURITY_MODEL.md e ADR-0002.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

_current_tenant_id: ContextVar[UUID | None] = ContextVar("current_tenant_id", default=None)


class TenantContextError(RuntimeError):
    """Levantado quando uma operacao tenant-scoped e chamada sem um tenant ativo no contexto."""


def get_current_tenant_id() -> UUID:
    tenant_id = _current_tenant_id.get()
    if tenant_id is None:
        raise TenantContextError(
            "Nenhum tenant ativo no contexto atual. "
            "Toda operacao TENANT precisa rodar dentro de 'with tenant_scope(tenant_id):'."
        )
    return tenant_id


def get_current_tenant_id_or_none() -> UUID | None:
    return _current_tenant_id.get()


@contextmanager
def tenant_scope(tenant_id: UUID):  # type: ignore[no-untyped-def]
    """Ativa um tenant_id para o bloco corrente (requisicao HTTP ou execucao de job)."""
    token = _current_tenant_id.set(tenant_id)
    try:
        yield tenant_id
    finally:
        _current_tenant_id.reset(token)
