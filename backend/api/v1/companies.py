"""Endpoint do CompanyProfile do tenant corrente — visualizar e (re)disparar enriquecimento
por CNPJ. Ver domains/procurement/companies/ para o modelo e o job de enriquecimento.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.deps import CurrentUser, get_current_user, require_role
from core.auth.models import Role
from core.db.session import tenant_session
from core.jobs.enqueue import get_arq_pool
from core.jobs.models import JobRun, JobStatus
from domains.procurement.companies.jobs import JOB_TYPE as ENRICH_COMPANY_PROFILE_JOB_TYPE
from domains.procurement.companies.models import CompanyProfile, EnrichmentStatus

router = APIRouter(prefix="/v1/company-profile", tags=["companies"])


class CompanyProfileResponse(BaseModel):
    id: UUID
    cnpj: str | None
    legal_name: str
    trade_name: str | None
    cnaes: list[dict[str, Any]]
    regions: list[str]
    products: list[str]
    services: list[str]
    enrichment_status: EnrichmentStatus
    enrichment_error: str | None

    model_config = {"from_attributes": True}


class UpdateCnpjRequest(BaseModel):
    cnpj: str = Field(min_length=11, max_length=18)


class UpdateCommercialProfileRequest(BaseModel):
    """O que o tenant declara vender e onde atua — entrada direta do Opportunity Engine (Fase 7).

    Os limites (20 termos, 120 caracteres) nao sao arbitrarios: cada termo declarado custa um
    embedding por edital avaliado no caminho semantico do matching, entao uma lista enorme
    multiplica o custo do funil sem melhorar a precisao (ver
    domains/procurement/opportunities/matching.py).
    """

    regions: list[str] = Field(default_factory=list, max_length=27)
    products: list[str] = Field(default_factory=list, max_length=20)
    services: list[str] = Field(default_factory=list, max_length=20)


async def _get_profile_or_404(tenant_id: UUID) -> CompanyProfile:
    async with tenant_session() as session:
        result = await session.execute(
            select(CompanyProfile).where(CompanyProfile.tenant_id == tenant_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise HTTPException(status_code=404, detail="CompanyProfile nao encontrado")
        return profile


@router.get("", response_model=CompanyProfileResponse)
async def get_company_profile(
    current_user: CurrentUser = Depends(get_current_user),
) -> CompanyProfile:
    return await _get_profile_or_404(current_user.tenant_id)


@router.put("/commercial", response_model=CompanyProfileResponse)
async def update_commercial_profile(
    payload: UpdateCommercialProfileRequest,
    current_user: CurrentUser = Depends(require_role(Role.OWNER, Role.ADMIN)),
) -> CompanyProfile:
    """Declara regioes/produtos/servicos. Sem isto o radar fica vazio de proposito: o matching
    nao cria Opportunity para um perfil sem produto/servico declarado (ver
    domains/procurement/opportunities/matching.py) — um radar de "todo edital do estado" seria
    ruido, nao valor.
    """
    async with tenant_session() as session:
        result = await session.execute(
            select(CompanyProfile).where(CompanyProfile.tenant_id == current_user.tenant_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise HTTPException(status_code=404, detail="CompanyProfile nao encontrado")

        profile.regions = [region.strip().upper() for region in payload.regions if region.strip()]
        profile.products = [term.strip() for term in payload.products if term.strip()]
        profile.services = [term.strip() for term in payload.services if term.strip()]

    return await _get_profile_or_404(current_user.tenant_id)


@router.put("/cnpj", response_model=CompanyProfileResponse)
async def update_cnpj(
    payload: UpdateCnpjRequest,
    current_user: CurrentUser = Depends(require_role(Role.OWNER, Role.ADMIN)),
) -> CompanyProfile:
    async with tenant_session() as session:
        result = await session.execute(
            select(CompanyProfile).where(CompanyProfile.tenant_id == current_user.tenant_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise HTTPException(status_code=404, detail="CompanyProfile nao encontrado")

        profile.cnpj = payload.cnpj
        profile.enrichment_status = EnrichmentStatus.PENDING
        await session.flush()

        job_run = JobRun(
            tenant_id=current_user.tenant_id,
            job_type=ENRICH_COMPANY_PROFILE_JOB_TYPE,
            status=JobStatus.PENDING,
            payload={"company_profile_id": str(profile.id)},
        )
        session.add(job_run)
        await session.flush()
        job_run_id = job_run.id
        profile_id = profile.id

    pool = await get_arq_pool()
    await pool.enqueue_job(
        "enrich_company_profile_job",
        str(job_run_id),
        str(current_user.tenant_id),
        str(profile_id),
    )

    return await _get_profile_or_404(current_user.tenant_id)
