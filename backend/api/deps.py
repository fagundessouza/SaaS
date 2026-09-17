"""Dependencias compartilhadas da API.

Substitui, na Fase 2, o placeholder de `X-Tenant-Id` da Fase 1 (ver git history de
api/deps.py) por autenticacao real via JWT no header `Authorization: Bearer <token>`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.auth.models import Role
from core.auth.security import InvalidTokenError, decode_access_token
from core.permissions.rbac import PermissionDeniedError, ensure_role
from core.tenancy.context import tenant_scope

_bearer_scheme = HTTPBearer(auto_error=True)


@dataclass(frozen=True)
class CurrentUser:
    user_id: UUID
    tenant_id: UUID
    role: Role


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> AsyncIterator[CurrentUser]:
    try:
        claims = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    with tenant_scope(claims.tenant_id):
        yield CurrentUser(user_id=claims.user_id, tenant_id=claims.tenant_id, role=claims.role)


def require_role(*allowed: Role):  # type: ignore[no-untyped-def]
    async def _dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        try:
            ensure_role(current_user.role, *allowed)
        except PermissionDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return current_user

    return _dependency
