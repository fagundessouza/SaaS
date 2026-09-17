"""Job periodico do Opportunity Engine: avalia os editais recentes contra o perfil de cada
tenant ativo.

Roda DEPOIS do ciclo de ingestao (ver worker.py: ingestao em {0,30}, matching em {15,45}) — nao
ha acoplamento direto entre os dois jobs de proposito: se a ingestao falhar num ciclo, o
matching simplesmente encontra menos editais novos, em vez de nao rodar.

Cada tenant e processado dentro do seu proprio `tenant_scope` (RLS ativo). O Tender e GLOBAL,
lido via `system_session`; a Opportunity e TENANT, escrita via `tenant_session`. Esta alternancia
e explicita e intencional — ver ADR-0002 e core/db/session.py.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from core.config import get_settings
from core.db.session import system_session, tenant_session
from core.observability.logging import get_logger
from core.observability.metrics import (
    job_duration_seconds,
    jobs_processed_total,
    opportunity_match_evaluations_total,
)
from core.tenancy.context import tenant_scope
from core.tenancy.models import Tenant, TenantStatus
from domains.procurement.companies.models import CompanyProfile
from domains.procurement.opportunities.matching import MatchProfile, evaluate_match
from domains.procurement.opportunities.models import Opportunity
from domains.procurement.opportunities.service import create_opportunity_from_match
from domains.procurement.tenders.models import Tender

logger = get_logger(__name__)

JOB_TYPE = "opportunity_matching"

# TRIAL conta como ativo: um tenant em avaliacao e justamente quem mais precisa ver o radar
# funcionando. SUSPENDED/CANCELLED nao geram Opportunity nova (mas as existentes permanecem —
# nada e apagado por mudanca de status de assinatura).
_MATCHABLE_TENANT_STATUSES = (TenantStatus.TRIAL, TenantStatus.ACTIVE)


async def _recent_tenders() -> list[tuple[uuid.UUID, str, str | None]]:
    lookback = get_settings().opportunity_matching_lookback_hours
    since = datetime.now(UTC) - timedelta(hours=lookback)
    async with system_session() as session:
        result = await session.execute(
            select(Tender.id, Tender.objeto, Tender.uf).where(Tender.updated_at >= since)
        )
        return [(row[0], row[1], row[2]) for row in result.all()]


async def _matchable_tenants() -> list[uuid.UUID]:
    async with system_session() as session:
        result = await session.execute(
            select(Tenant.id).where(Tenant.status.in_(_MATCHABLE_TENANT_STATUSES))
        )
        return list(result.scalars().all())


async def _load_profile(tenant_id: uuid.UUID) -> MatchProfile | None:
    async with tenant_session() as session:
        result = await session.execute(
            select(CompanyProfile).where(CompanyProfile.tenant_id == tenant_id)
        )
        profile = result.scalars().first()
        if profile is None:
            return None
        return MatchProfile(
            regions=list(profile.regions),
            products=list(profile.products),
            services=list(profile.services),
        )


async def _already_evaluated_tender_ids(tenant_id: uuid.UUID) -> set[uuid.UUID]:
    async with tenant_session() as session:
        result = await session.execute(
            select(Opportunity.tender_id).where(Opportunity.tenant_id == tenant_id)
        )
        return set(result.scalars().all())


async def run_opportunity_matching_job(ctx: dict[str, Any]) -> dict[str, int]:
    started_at = time.monotonic()
    counts = {"tenants": 0, "evaluated": 0, "matched": 0}

    tenders = await _recent_tenders()
    if not tenders:
        logger.info("opportunity_matching.no_recent_tenders")

    for tenant_id in await _matchable_tenants():
        with tenant_scope(tenant_id):
            profile = await _load_profile(tenant_id)
            if profile is None:
                # Tenant sem CompanyProfile (ainda em onboarding): nada a casar. Nao e erro.
                continue

            counts["tenants"] += 1
            already_seen = await _already_evaluated_tender_ids(tenant_id)

            for tender_id, objeto, uf in tenders:
                if tender_id in already_seen:
                    continue

                counts["evaluated"] += 1
                evaluation = await evaluate_match(objeto=objeto, tender_uf=uf, profile=profile)
                outcome = "matched" if evaluation.matched else "rejected"
                opportunity_match_evaluations_total.labels(outcome=outcome).inc()

                if not evaluation.matched:
                    continue

                created = await create_opportunity_from_match(
                    tenant_id=tenant_id, tender_id=tender_id, evaluation=evaluation
                )
                if created is not None:
                    counts["matched"] += 1

    duration = time.monotonic() - started_at
    job_duration_seconds.labels(job_type=JOB_TYPE).observe(duration)
    jobs_processed_total.labels(job_type=JOB_TYPE, status="completed").inc()
    logger.info("opportunity_matching.completed", duration_s=round(duration, 2), **counts)
    return counts
