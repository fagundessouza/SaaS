"""Isolamento de tenant para as tabelas da Fase 10 (alerts, notification_preferences,
push_subscriptions, notifications) — mesmo padrao de tests/security/test_analysis_isolation.py
(Fase 8): prova a barreira em duas camadas, a query de dominio (sem filtro manual de tenant_id,
confia no RLS) e o caminho fim a fim pela API com token de outro tenant.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
from sqlalchemy import select

from api.main import app
from core.auth.service import create_tenant_with_owner
from core.db.session import tenant_session
from core.notifications.models import (
    Alert,
    Notification,
    NotificationChannelType,
    NotificationPreference,
    PushSubscription,
)
from core.notifications.preferences_service import set_preference
from core.notifications.push_subscriptions_service import create_push_subscription
from core.notifications.service import create_alert_and_dispatch
from core.tenancy.context import tenant_scope
from tests.conftest import unique_email


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_tenant_with_notification_data(prefix: str) -> uuid.UUID:
    owner = await create_tenant_with_owner(
        company_name=f"Empresa {prefix}", email=unique_email(prefix), password="senha-forte-123"
    )

    with tenant_scope(owner.tenant_id):
        await set_preference(
            tenant_id=owner.tenant_id,
            user_id=owner.user_id,
            topic="TenderUpdated",
            channel=NotificationChannelType.EMAIL,
            enabled=True,
        )
        await create_push_subscription(
            tenant_id=owner.tenant_id,
            user_id=owner.user_id,
            endpoint=f"https://push.exemplo.com/{uuid.uuid4()}",
            p256dh_key="fake-p256dh",
            auth_key="fake-auth",
        )
        await create_alert_and_dispatch(
            tenant_id=owner.tenant_id,
            user_id=owner.user_id,
            topic="OpportunityMatched",
            payload={"tender_id": "abc"},
            source_event_id=uuid.uuid4(),
        )

    return owner.tenant_id


async def test_notification_tables_of_one_tenant_are_invisible_to_another() -> None:
    tenant_a = await _create_tenant_with_notification_data("notif-isola-a")
    tenant_b = await _create_tenant_with_notification_data("notif-isola-b")

    # Query do tenant B nao filtra tenant_id de proposito: quem tem de barrar e o RLS.
    with tenant_scope(tenant_b):
        async with tenant_session() as session:
            alerts = (await session.execute(select(Alert))).scalars().all()
            notifications = (await session.execute(select(Notification))).scalars().all()
            preferences = (
                await session.execute(select(NotificationPreference))
            ).scalars().all()
            subscriptions = (await session.execute(select(PushSubscription))).scalars().all()

    assert all(row.tenant_id == tenant_b for row in alerts)
    assert all(row.tenant_id == tenant_b for row in notifications)
    assert all(row.tenant_id == tenant_b for row in preferences)
    assert all(row.tenant_id == tenant_b for row in subscriptions)
    assert tenant_a not in {row.tenant_id for row in alerts}


async def test_api_token_of_another_tenant_cannot_see_notifications_inbox(
    client: httpx.AsyncClient,
) -> None:
    await _create_tenant_with_notification_data("notif-isola-api-a")

    signup_b = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "Empresa B Notif",
            "email": unique_email("notif-isola-api-b"),
            "password": "senha-forte-123",
        },
    )
    token_b = signup_b.json()["access_token"]

    response = await client.get(
        "/v1/notifications", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert response.status_code == 200
    assert response.json() == []  # inbox do tenant A nao vaza para o tenant B
