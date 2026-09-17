"""Endpoint de leitura do Tenant corrente.

O bootstrap aberto `POST /v1/tenants` da Fase 1 foi removido — criar um tenant agora sempre
passa por `POST /v1/auth/signup` (cria Tenant + User owner + Subscription trial + CompanyProfile
juntos, ver api/onboarding.py).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import CurrentUser, get_current_user
from core.db.session import system_session
from core.tenancy.models import Tenant, TenantStatus

router = APIRouter(prefix="/v1/tenants", tags=["tenants"])


class TenantResponse(BaseModel):
    id: UUID
    name: str
    status: TenantStatus

    model_config = {"from_attributes": True}


@router.get("/me", response_model=TenantResponse)
async def get_current_tenant(current_user: CurrentUser = Depends(get_current_user)) -> Tenant:
    async with system_session() as session:
        tenant = await session.get(Tenant, current_user.tenant_id)
        assert tenant is not None  # garantido por um access token valido
        return tenant
