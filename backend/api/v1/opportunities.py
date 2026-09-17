"""Radar do tenant: as Opportunity descobertas pelo Opportunity Engine e seu ciclo de vida.

Tudo aqui e TENANT (ao contrario de api/v1/tenders.py, que serve conteudo GLOBAL): o escopo vem
do RLS via `tenant_session` no dominio, nunca de um filtro manual — ver ADR-0002.

A resposta expoe `compatibility` e `confidence` decompostos, e NAO um score unico agregado: a
apresentacao pode resumir, o contrato da API nao esconde os fatores (ver
docs/00-CRITICAL_ANALYSIS.md, item 5 da tabela de ambiguidades).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.deps import CurrentUser, get_current_user
from domains.procurement.analysis.models import EvidenceKind, FindingSeverity, FindingStatus
from domains.procurement.analysis.service import (
    AnalysisNotFoundError,
    CompanyProfileNotFoundError,
    generate_analysis,
    get_analysis_with_findings,
)
from domains.procurement.analysis.service import (
    OpportunityNotFoundError as AnalysisOpportunityNotFoundError,
)
from domains.procurement.opportunities.models import OpportunityStatus
from domains.procurement.opportunities.service import (
    InvalidStatusTransitionError,
    OpportunityNotFoundError,
    assign_opportunity,
    list_opportunities,
    transition_status,
)
from domains.procurement.tenders.models import RequirementCategory

router = APIRouter(prefix="/v1/opportunities", tags=["opportunities"])


class OpportunityResponse(BaseModel):
    id: UUID
    tender_id: UUID
    status: OpportunityStatus
    assigned_to_user_id: UUID | None
    created_at: datetime
    compatibility: dict[str, Any]
    confidence: dict[str, float]


class TransitionStatusRequest(BaseModel):
    status: OpportunityStatus


class AssignRequest(BaseModel):
    user_id: UUID | None


@router.get("", response_model=list[OpportunityResponse])
async def list_radar(
    status: OpportunityStatus | None = Query(default=None),
    only_active: bool = Query(
        default=False,
        description="Apenas oportunidades em andamento (exclui won/lost/withdrawn). "
        "Ignorado quando `status` e informado.",
    ),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[OpportunityResponse]:
    rows = await list_opportunities(status=status, only_active=only_active)
    return [
        OpportunityResponse(
            id=opportunity.id,
            tender_id=opportunity.tender_id,
            status=opportunity.status,
            assigned_to_user_id=opportunity.assigned_to_user_id,
            created_at=opportunity.created_at,
            compatibility=match.compatibility if match is not None else {},
            confidence=match.confidence if match is not None else {},
        )
        for opportunity, match in rows
    ]


@router.patch("/{opportunity_id}/status", response_model=OpportunityResponse)
async def change_status(
    opportunity_id: UUID,
    request: TransitionStatusRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> OpportunityResponse:
    try:
        opportunity = await transition_status(
            opportunity_id=opportunity_id, requested=request.status
        )
    except OpportunityNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Oportunidade nao encontrada") from exc
    except InvalidStatusTransitionError as exc:
        # 409: o pedido esta bem formado, mas conflita com o estado atual do recurso — nao e um
        # erro de validacao de payload (422), que e como o FastAPI trataria um status inexistente.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return OpportunityResponse(
        id=opportunity.id,
        tender_id=opportunity.tender_id,
        status=opportunity.status,
        assigned_to_user_id=opportunity.assigned_to_user_id,
        created_at=opportunity.created_at,
        compatibility={},
        confidence={},
    )


# --- Analysis (dossie, Fase 8) ---


class EvidenceResponse(BaseModel):
    kind: EvidenceKind
    description: str
    document_version_id: UUID | None
    section: str | None
    page_start: int | None
    page_end: int | None
    excerpt: str | None
    certificate_id: UUID | None
    attestation_id: UUID | None

    model_config = {"from_attributes": True}


class FindingResponse(BaseModel):
    id: UUID
    category: RequirementCategory
    status: FindingStatus
    severity: FindingSeverity
    summary: str
    evidence: list[EvidenceResponse]


class AnalysisResponse(BaseModel):
    id: UUID
    opportunity_id: UUID
    generated_at: datetime
    findings: list[FindingResponse]


@router.get("/{opportunity_id}/analysis", response_model=AnalysisResponse)
async def get_analysis(
    opportunity_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> AnalysisResponse:
    try:
        analysis, findings = await get_analysis_with_findings(opportunity_id)
    except AnalysisNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Nenhuma analise gerada para esta oportunidade ainda "
            "(POST neste mesmo endpoint para gerar)",
        ) from exc

    return AnalysisResponse(
        id=analysis.id,
        opportunity_id=analysis.opportunity_id,
        generated_at=analysis.generated_at,
        findings=[
            FindingResponse(
                id=finding.id,
                category=finding.category,
                status=finding.status,
                severity=finding.severity,
                summary=finding.summary,
                evidence=[EvidenceResponse.model_validate(e) for e in evidence],
            )
            for finding, evidence in findings
        ],
    )


@router.post("/{opportunity_id}/analysis", response_model=AnalysisResponse, status_code=201)
async def create_analysis(
    opportunity_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> AnalysisResponse:
    """Gera (ou regenera, substituindo a anterior — ver domains/procurement/analysis/service.py)
    o dossie desta Opportunity. Nunca automatico: so dispara quando o usuario pede, aqui."""
    try:
        await generate_analysis(opportunity_id)
    except AnalysisOpportunityNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Oportunidade nao encontrada") from exc
    except CompanyProfileNotFoundError as exc:
        raise HTTPException(
            status_code=422, detail="CompanyProfile do tenant nao encontrado"
        ) from exc

    return await get_analysis(opportunity_id, current_user)


@router.patch("/{opportunity_id}/assignee", response_model=OpportunityResponse)
async def change_assignee(
    opportunity_id: UUID,
    request: AssignRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> OpportunityResponse:
    try:
        opportunity = await assign_opportunity(
            opportunity_id=opportunity_id, user_id=request.user_id
        )
    except OpportunityNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Oportunidade nao encontrada") from exc

    return OpportunityResponse(
        id=opportunity.id,
        tender_id=opportunity.tender_id,
        status=opportunity.status,
        assigned_to_user_id=opportunity.assigned_to_user_id,
        created_at=opportunity.created_at,
        compatibility={},
        confidence={},
    )
