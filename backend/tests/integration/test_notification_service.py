"""create_alert_and_dispatch contra Postgres real (sem mock) — ver
core/notifications/service.py."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from core.auth.service import create_tenant_with_owner
from core.db.session import tenant_session
from core.notifications.models import Alert, DeliveryStatus, Notification, NotificationChannelType
from core.notifications.preferences_service import set_preference
from core.notifications.service import create_alert_and_dispatch
from core.tenancy.context import tenant_scope
from tests.conftest import unique_email


async def test_create_alert_and_dispatch_creates_alert_and_notifications_per_channel() -> None:
    owner = await create_tenant_with_owner(
        company_name="Empresa Notif", email=unique_email("notif-dispatch"),
        password="senha-forte-123",
    )
    event_id = uuid.uuid4()

    with tenant_scope(owner.tenant_id):
        alert_id = await create_alert_and_dispatch(
            tenant_id=owner.tenant_id,
            user_id=owner.user_id,
            topic="TenderUpdated",
            payload={"tender_id": "abc", "external_id": "X-1-000001/2026", "version_number": 2},
            source_event_id=event_id,
        )
        assert alert_id is not None

        async with tenant_session() as session:
            alert = await session.get(Alert, alert_id)
            assert alert is not None
            assert alert.topic == "TenderUpdated"
            assert alert.source_event_id == event_id

            notifications = (
                await session.execute(
                    select(Notification).where(Notification.alert_id == alert_id)
                )
            ).scalars().all()

        channels = {n.channel for n in notifications}
        assert channels == {NotificationChannelType.EMAIL, NotificationChannelType.WEB_PUSH}
        assert all(n.status == DeliveryStatus.SENT for n in notifications)  # canais console


async def test_create_alert_and_dispatch_is_idempotent_for_same_event_and_user() -> None:
    owner = await create_tenant_with_owner(
        company_name="Empresa Notif Idem", email=unique_email("notif-idem"),
        password="senha-forte-123",
    )
    event_id = uuid.uuid4()

    with tenant_scope(owner.tenant_id):
        first = await create_alert_and_dispatch(
            tenant_id=owner.tenant_id,
            user_id=owner.user_id,
            topic="OpportunityMatched",
            payload={"tender_id": "abc"},
            source_event_id=event_id,
        )
        second = await create_alert_and_dispatch(
            tenant_id=owner.tenant_id,
            user_id=owner.user_id,
            topic="OpportunityMatched",
            payload={"tender_id": "abc"},
            source_event_id=event_id,
        )

        assert first is not None
        assert second is None  # reentrega descartada, nao duplicou o Alert

        async with tenant_session() as session:
            alerts = (
                await session.execute(
                    select(Alert).where(Alert.source_event_id == event_id)
                )
            ).scalars().all()
        assert len(alerts) == 1


async def test_create_alert_and_dispatch_skips_disabled_channel() -> None:
    owner = await create_tenant_with_owner(
        company_name="Empresa Notif Pref", email=unique_email("notif-pref"),
        password="senha-forte-123",
    )

    with tenant_scope(owner.tenant_id):
        await set_preference(
            tenant_id=owner.tenant_id,
            user_id=owner.user_id,
            topic="AnalysisCompleted",
            channel=NotificationChannelType.WEB_PUSH,
            enabled=False,
        )

        alert_id = await create_alert_and_dispatch(
            tenant_id=owner.tenant_id,
            user_id=owner.user_id,
            topic="AnalysisCompleted",
            payload={"opportunity_id": "opp-1"},
            source_event_id=uuid.uuid4(),
        )
        assert alert_id is not None

        async with tenant_session() as session:
            notifications = (
                await session.execute(
                    select(Notification).where(Notification.alert_id == alert_id)
                )
            ).scalars().all()

        channels = {n.channel for n in notifications}
        assert channels == {NotificationChannelType.EMAIL}  # web_push desabilitado, nao criado
