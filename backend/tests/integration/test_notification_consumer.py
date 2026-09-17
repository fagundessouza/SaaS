"""Pipeline completo do Notification Engine contra Postgres + Redis reais (sem mock): outbox ->
dispatch -> Redis Stream -> consumidor -> Alert/Notification. Mesmo comportamento que o worker
real veria (ver core/events/dispatcher.py e domains/notifications/consumer.py)."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from core.auth.service import create_tenant_with_owner
from core.db.session import system_session, tenant_session
from core.events.dispatcher import dispatch_pending_events
from core.events.publisher import publish_event
from core.notifications.models import Alert
from core.tenancy.context import tenant_scope
from domains.notifications.consumer import consume_notification_events_job
from domains.procurement.opportunities.models import Opportunity
from domains.procurement.tenders.models import Tender
from tests.conftest import unique_email


async def _create_tender() -> uuid.UUID:
    async with system_session() as session:
        tender = Tender(
            source="pncp",
            external_id=f"notif-consumer-{uuid.uuid4()}",
            orgao_cnpj="00394460000141",
            orgao_nome="Orgao Teste",
            unidade_nome=None,
            uf="RN",
            municipio="Cidade Teste",
            modalidade="Pregao Eletronico",
            objeto="Objeto teste",
            valor_estimado=None,
            data_publicacao=date(2026, 9, 17),
            data_abertura_proposta=None,
            data_encerramento_proposta=None,
            situacao=None,
            latest_version_number=1,
        )
        session.add(tender)
        await session.flush()
        return tender.id


async def test_tender_updated_notifies_only_tenants_with_an_opportunity_for_it() -> None:
    tender_id = await _create_tender()

    with_opportunity = await create_tenant_with_owner(
        company_name="Com Oportunidade", email=unique_email("notif-with-opp"),
        password="senha-forte-123",
    )
    without_opportunity = await create_tenant_with_owner(
        company_name="Sem Oportunidade", email=unique_email("notif-without-opp"),
        password="senha-forte-123",
    )

    with tenant_scope(with_opportunity.tenant_id):
        async with tenant_session() as session:
            session.add(
                Opportunity(tenant_id=with_opportunity.tenant_id, tender_id=tender_id)
            )

    async with system_session() as session:
        await publish_event(
            session,
            topic="TenderUpdated",
            payload={"tender_id": str(tender_id), "external_id": "x", "version_number": 2},
            tenant_id=None,
        )

    await dispatch_pending_events()
    counts = await consume_notification_events_job({})
    assert counts["processed"] >= 1

    with tenant_scope(with_opportunity.tenant_id):
        async with tenant_session() as session:
            alerts = (
                await session.execute(select(Alert).where(Alert.topic == "TenderUpdated"))
            ).scalars().all()
        assert len(alerts) == 1
        assert alerts[0].user_id == with_opportunity.user_id

    with tenant_scope(without_opportunity.tenant_id):
        async with tenant_session() as session:
            alerts = (
                await session.execute(select(Alert).where(Alert.topic == "TenderUpdated"))
            ).scalars().all()
        assert alerts == []  # nao tem Opportunity para este Tender, nao e notificado


async def test_consumer_is_idempotent_across_consecutive_runs() -> None:
    """Segunda rodada do consumidor sem novo evento no stream = nao processa nada de novo (ver
    docstring de domains/notifications/consumer.py sobre XACK)."""
    tender_id = await _create_tender()
    owner = await create_tenant_with_owner(
        company_name="Empresa Idem Consumer", email=unique_email("notif-consumer-idem"),
        password="senha-forte-123",
    )

    with tenant_scope(owner.tenant_id):
        async with tenant_session() as session:
            session.add(Opportunity(tenant_id=owner.tenant_id, tender_id=tender_id))

    async with system_session() as session:
        await publish_event(
            session,
            topic="TenderUpdated",
            payload={"tender_id": str(tender_id), "external_id": "y", "version_number": 3},
            tenant_id=None,
        )

    await dispatch_pending_events()
    first = await consume_notification_events_job({})
    second = await consume_notification_events_job({})

    assert first["processed"] >= 1
    assert second["processed"] == 0
    assert second["skipped"] == 0

    with tenant_scope(owner.tenant_id):
        async with tenant_session() as session:
            alerts = (
                await session.execute(select(Alert).where(Alert.topic == "TenderUpdated"))
            ).scalars().all()
        assert len(alerts) == 1  # nao duplicou


async def test_opportunity_matched_notifies_the_known_tenant_directly() -> None:
    owner = await create_tenant_with_owner(
        company_name="Empresa Match Direto", email=unique_email("notif-match-direct"),
        password="senha-forte-123",
    )

    async with system_session() as session:
        await publish_event(
            session,
            topic="OpportunityMatched",
            payload={"opportunity_id": "opp-x", "tender_id": "tender-x"},
            tenant_id=owner.tenant_id,
        )

    await dispatch_pending_events()
    await consume_notification_events_job({})

    with tenant_scope(owner.tenant_id):
        async with tenant_session() as session:
            alerts = (
                await session.execute(
                    select(Alert).where(Alert.topic == "OpportunityMatched")
                )
            ).scalars().all()
        assert len(alerts) == 1
        assert alerts[0].user_id == owner.user_id
