"""CRUD de Attestation do CompanyProfile do tenant corrente (Fase 8)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from core.db.session import tenant_session
from domains.procurement.companies.models import Attestation


class AttestationNotFoundError(Exception):
    pass


async def create_attestation(
    *,
    tenant_id: uuid.UUID,
    company_profile_id: uuid.UUID,
    issuing_org: str,
    object_description: str,
    contract_value: Decimal | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> Attestation:
    async with tenant_session() as session:
        attestation = Attestation(
            tenant_id=tenant_id,
            company_profile_id=company_profile_id,
            issuing_org=issuing_org,
            object_description=object_description,
            contract_value=contract_value,
            period_start=period_start,
            period_end=period_end,
        )
        session.add(attestation)
        await session.flush()
        return attestation


async def list_attestations(*, company_profile_id: uuid.UUID) -> list[Attestation]:
    async with tenant_session() as session:
        result = await session.execute(
            select(Attestation)
            .where(Attestation.company_profile_id == company_profile_id)
            .order_by(Attestation.issuing_org)
        )
        return list(result.scalars().all())


async def delete_attestation(*, attestation_id: uuid.UUID) -> None:
    async with tenant_session() as session:
        attestation = await session.get(Attestation, attestation_id)
        if attestation is None:
            raise AttestationNotFoundError(str(attestation_id))
        await session.delete(attestation)
