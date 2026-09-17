"""Consulta de TenderItem e Requirement de um Tender (Fase 6) — qualquer usuario autenticado
pode consultar, mesmo raciocinio de api/v1/knowledge.py: o conteudo e sempre GLOBAL (edital
publicado e informacao publica, ver DOMAIN_MODEL.md), sem escopo de tenant.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from api.deps import CurrentUser, get_current_user
from core.db.session import system_session
from domains.procurement.tenders.models import Requirement, RequirementCategory, TenderItem

router = APIRouter(prefix="/v1/tenders", tags=["tenders"])


class TenderItemResponse(BaseModel):
    id: UUID
    item_number: int
    description: str
    material_or_service: str | None
    quantity: float | None
    unit_of_measure: str | None
    unit_estimated_value: float | None
    total_estimated_value: float | None

    model_config = {"from_attributes": True}


class RequirementResponse(BaseModel):
    id: UUID
    category: RequirementCategory
    description: str
    confidence: float
    document_version_id: UUID
    section: str | None
    page_start: int
    page_end: int

    model_config = {"from_attributes": True}


@router.get("/{tender_id}/items", response_model=list[TenderItemResponse])
async def list_tender_items(
    tender_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[TenderItemResponse]:
    async with system_session() as session:
        items = (
            (
                await session.execute(
                    select(TenderItem)
                    .where(TenderItem.tender_id == tender_id)
                    .order_by(TenderItem.item_number)
                )
            )
            .scalars()
            .all()
        )
        return [TenderItemResponse.model_validate(item) for item in items]


@router.get("/{tender_id}/requirements", response_model=list[RequirementResponse])
async def list_tender_requirements(
    tender_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[RequirementResponse]:
    async with system_session() as session:
        requirements = (
            (await session.execute(select(Requirement).where(Requirement.tender_id == tender_id)))
            .scalars()
            .all()
        )
        return [RequirementResponse.model_validate(req) for req in requirements]
