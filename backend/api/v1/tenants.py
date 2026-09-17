"""Endpoints de Tenant.

NOTA DE ESCOPO (Fase 1): `POST /v1/tenants` e um bootstrap deliberadamente aberto para permitir
criar tenants de teste antes de existir onboarding real (Fase 2). Isso NAO e o fluxo de
cadastro de produto — sera substituido por um fluxo de signup com autenticacao antes de qualquer
ambiente exposto publicamente.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import require_tenant
from core.db.session import system_session
from core.tenancy.models import Tenant, TenantStatus

router = APIRouter(prefix="/v1/tenants", tags=["tenants"])


class CreateTenantRequest(BaseModel):
    name: str


class TenantResponse(BaseModel):
    id: UUID
    name: str
    status: TenantStatus

    model_config = {"from_attributes": True}


@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(payload: CreateTenantRequest) -> Tenant:
    async with system_session() as session:
        tenant = Tenant(name=payload.name)
        session.add(tenant)
        await session.flush()
        await session.refresh(tenant)
        return tenant


@router.get("/me", response_model=TenantResponse)
async def get_current_tenant(tenant_id: UUID = Depends(require_tenant)) -> Tenant:
    async with system_session() as session:
        tenant = await session.get(Tenant, tenant_id)
        assert tenant is not None  # garantido por require_tenant
        return tenant
