"""Roteamento de topico de evento de dominio -> quais usuarios notificar. Vive em `domains/`
(nao `core/`) porque precisa ler `Opportunity`/`User` cross-domain — `core/notifications`
(generico, ver core/notifications/service.py) nao pode importar `domains` (ADR-0001).

Um handler por topico do catalogo (ver docs/EVENT_AND_NOTIFICATION_ARCHITECTURE.md) que ja tem
producer real. Topico sem handler aqui e simplesmente ignorado pelo consumidor (ver
domains/notifications/consumer.py) — nunca uma excecao: um topico novo no outbox nao pode
derrubar o Notification Engine.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from core.auth.models import User
from core.db.session import system_session, tenant_session
from core.notifications.service import create_alert_and_dispatch
from core.observability.logging import get_logger
from core.tenancy.context import tenant_scope
from core.tenancy.models import Tenant
from domains.procurement.opportunities.models import Opportunity

logger = get_logger(__name__)

_Payload = dict[str, object]


async def _notify_active_users_of_tenant(
    tenant_id: uuid.UUID, topic: str, payload: _Payload, event_id: uuid.UUID
) -> None:
    with tenant_scope(tenant_id):
        async with tenant_session() as session:
            user_ids = list(
                (
                    await session.execute(
                        select(User.id).where(
                            User.tenant_id == tenant_id, User.is_active.is_(True)
                        )
                    )
                )
                .scalars()
                .all()
            )

        for user_id in user_ids:
            await create_alert_and_dispatch(
                tenant_id=tenant_id,
                user_id=user_id,
                topic=topic,
                payload=payload,
                source_event_id=event_id,
            )


async def handle_tender_updated(
    tenant_id: uuid.UUID | None, payload: _Payload, event_id: uuid.UUID
) -> None:
    """`TenderUpdated` nao carrega tenant_id (Tender e GLOBAL, ver
    domains/procurement/tenders/service.py) — precisa varrer todo tenant e checar quem tem
    Opportunity para este Tender (mesmo padrao de iteracao ja usado por
    domains/procurement/opportunities/jobs.py::run_opportunity_matching_job, pela mesma razao:
    Opportunity tem FORCE ROW LEVEL SECURITY, entao nao ha como fazer uma unica query
    cross-tenant sem um bypass de RLS que este projeto nao introduz sem deliberacao propria)."""
    tender_id = uuid.UUID(str(payload["tender_id"]))

    async with system_session() as session:
        all_tenant_ids = list((await session.execute(select(Tenant.id))).scalars().all())

    for candidate_tenant_id in all_tenant_ids:
        with tenant_scope(candidate_tenant_id):
            async with tenant_session() as session:
                has_opportunity = (
                    await session.execute(
                        select(Opportunity.id).where(Opportunity.tender_id == tender_id).limit(1)
                    )
                ).scalar_one_or_none()

        if has_opportunity is not None:
            await _notify_active_users_of_tenant(
                candidate_tenant_id, "TenderUpdated", payload, event_id
            )


async def handle_opportunity_matched(
    tenant_id: uuid.UUID | None, payload: _Payload, event_id: uuid.UUID
) -> None:
    if tenant_id is None:
        logger.error("notification.opportunity_matched_without_tenant", payload=payload)
        return
    await _notify_active_users_of_tenant(tenant_id, "OpportunityMatched", payload, event_id)


async def handle_analysis_completed(
    tenant_id: uuid.UUID | None, payload: _Payload, event_id: uuid.UUID
) -> None:
    if tenant_id is None:
        logger.error("notification.analysis_completed_without_tenant", payload=payload)
        return
    await _notify_active_users_of_tenant(tenant_id, "AnalysisCompleted", payload, event_id)


EventHandler = Callable[[uuid.UUID | None, _Payload, uuid.UUID], Awaitable[None]]

HANDLERS: dict[str, EventHandler] = {
    "TenderUpdated": handle_tender_updated,
    "OpportunityMatched": handle_opportunity_matched,
    "AnalysisCompleted": handle_analysis_completed,
}
