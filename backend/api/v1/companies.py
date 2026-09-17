"""Endpoint do CompanyProfile do tenant corrente — visualizar e (re)disparar enriquecimento
por CNPJ. Ver domains/procurement/companies/ para o modelo e o job de enriquecimento.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
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
from domains.procurement.companies.attestations_service import (
    AttestationNotFoundError,
    create_attestation,
    delete_attestation,
    list_attestations,
)
from domains.procurement.companies.certificates_service import (
    CertificateNotFoundError,
    create_certificate,
    delete_certificate,
    list_certificates,
)
from domains.procurement.companies.jobs import JOB_TYPE as ENRICH_COMPANY_PROFILE_JOB_TYPE
from domains.procurement.companies.models import CompanyProfile, EnrichmentStatus
from domains.procurement.tenders.models import RequirementCategory

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


# --- Certificate / Attestation (Fase 8 — evidencia usada por domains/procurement/analysis) ---


class CertificateResponse(BaseModel):
    id: UUID
    category: RequirementCategory
    name: str
    issued_at: date | None
    expires_at: date | None
    notes: str | None

    model_config = {"from_attributes": True}


class CreateCertificateRequest(BaseModel):
    category: RequirementCategory
    name: str = Field(min_length=1, max_length=255)
    issued_at: date | None = None
    expires_at: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class AttestationResponse(BaseModel):
    id: UUID
    issuing_org: str
    object_description: str
    contract_value: Decimal | None
    period_start: date | None
    period_end: date | None

    model_config = {"from_attributes": True}


class CreateAttestationRequest(BaseModel):
    issuing_org: str = Field(min_length=1, max_length=255)
    object_description: str = Field(min_length=1)
    contract_value: Decimal | None = None
    period_start: date | None = None
    period_end: date | None = None


@router.get("/certificates", response_model=list[CertificateResponse])
async def get_certificates(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[CertificateResponse]:
    profile = await _get_profile_or_404(current_user.tenant_id)
    certificates = await list_certificates(company_profile_id=profile.id)
    return [CertificateResponse.model_validate(c) for c in certificates]


@router.post("/certificates", response_model=CertificateResponse, status_code=201)
async def add_certificate(
    payload: CreateCertificateRequest,
    current_user: CurrentUser = Depends(require_role(Role.OWNER, Role.ADMIN)),
) -> CertificateResponse:
    profile = await _get_profile_or_404(current_user.tenant_id)
    certificate = await create_certificate(
        tenant_id=current_user.tenant_id,
        company_profile_id=profile.id,
        category=payload.category,
        name=payload.name,
        issued_at=payload.issued_at,
        expires_at=payload.expires_at,
        notes=payload.notes,
    )
    return CertificateResponse.model_validate(certificate)


@router.delete("/certificates/{certificate_id}", status_code=204)
async def remove_certificate(
    certificate_id: UUID,
    current_user: CurrentUser = Depends(require_role(Role.OWNER, Role.ADMIN)),
) -> None:
    try:
        await delete_certificate(certificate_id=certificate_id)
    except CertificateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Certidao nao encontrada") from exc


@router.get("/attestations", response_model=list[AttestationResponse])
async def get_attestations(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[AttestationResponse]:
    profile = await _get_profile_or_404(current_user.tenant_id)
    attestations = await list_attestations(company_profile_id=profile.id)
    return [AttestationResponse.model_validate(a) for a in attestations]


@router.post("/attestations", response_model=AttestationResponse, status_code=201)
async def add_attestation(
    payload: CreateAttestationRequest,
    current_user: CurrentUser = Depends(require_role(Role.OWNER, Role.ADMIN)),
) -> AttestationResponse:
    profile = await _get_profile_or_404(current_user.tenant_id)
    attestation = await create_attestation(
        tenant_id=current_user.tenant_id,
        company_profile_id=profile.id,
        issuing_org=payload.issuing_org,
        object_description=payload.object_description,
        contract_value=payload.contract_value,
        period_start=payload.period_start,
        period_end=payload.period_end,
    )
    return AttestationResponse.model_validate(attestation)


@router.delete("/attestations/{attestation_id}", status_code=204)
async def remove_attestation(
    attestation_id: UUID,
    current_user: CurrentUser = Depends(require_role(Role.OWNER, Role.ADMIN)),
) -> None:
    try:
        await delete_attestation(attestation_id=attestation_id)
    except AttestationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Atestado nao encontrado") from exc
