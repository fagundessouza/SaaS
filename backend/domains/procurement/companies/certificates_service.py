"""CRUD de Certificate do CompanyProfile do tenant corrente (Fase 8). Sem verificacao externa
automatica nesta fase — ver docstring de Certificate em models.py e DECISOES do
docs/phase-reports/FASE_8_REPORT.md.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from core.db.session import tenant_session
from domains.procurement.companies.models import Certificate
from domains.procurement.tenders.models import RequirementCategory


class CertificateNotFoundError(Exception):
    pass


async def create_certificate(
    *,
    tenant_id: uuid.UUID,
    company_profile_id: uuid.UUID,
    category: RequirementCategory,
    name: str,
    issued_at: date | None,
    expires_at: date | None,
    notes: str | None = None,
) -> Certificate:
    async with tenant_session() as session:
        certificate = Certificate(
            tenant_id=tenant_id,
            company_profile_id=company_profile_id,
            category=category,
            name=name,
            issued_at=issued_at,
            expires_at=expires_at,
            notes=notes,
        )
        session.add(certificate)
        await session.flush()
        return certificate


async def list_certificates(*, company_profile_id: uuid.UUID) -> list[Certificate]:
    async with tenant_session() as session:
        result = await session.execute(
            select(Certificate)
            .where(Certificate.company_profile_id == company_profile_id)
            .order_by(Certificate.category, Certificate.name)
        )
        return list(result.scalars().all())


async def delete_certificate(*, certificate_id: uuid.UUID) -> None:
    async with tenant_session() as session:
        certificate = await session.get(Certificate, certificate_id)
        if certificate is None:
            raise CertificateNotFoundError(str(certificate_id))
        await session.delete(certificate)
