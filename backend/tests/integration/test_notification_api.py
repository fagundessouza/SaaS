"""API de notificacoes: inbox, preferencias, assinaturas de Web Push (ver
api/v1/notifications.py)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest

from api.main import app
from core.db.session import system_session
from core.events.dispatcher import dispatch_pending_events
from core.events.publisher import publish_event
from domains.notifications.consumer import consume_notification_events_job
from tests.conftest import unique_email


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _signup(client: httpx.AsyncClient, prefix: str) -> tuple[str, uuid.UUID]:
    signup = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": f"Empresa {prefix}",
            "email": unique_email(prefix),
            "password": "senha-forte-123",
        },
    )
    assert signup.status_code == 201, signup.text
    body = signup.json()
    return str(body["access_token"]), uuid.UUID(body["tenant_id"])


async def test_notifications_require_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/notifications")).status_code == 401
    assert (await client.get("/v1/notifications/preferences")).status_code == 401


async def test_set_and_list_preferences(client: httpx.AsyncClient) -> None:
    token, _ = await _signup(client, "notif-pref-api")
    headers = {"Authorization": f"Bearer {token}"}

    update = await client.put(
        "/v1/notifications/preferences",
        headers=headers,
        json={"topic": "TenderUpdated", "channel": "web_push", "enabled": False},
    )
    assert update.status_code == 200, update.text
    assert update.json() == {"topic": "TenderUpdated", "channel": "web_push", "enabled": False}

    listing = await client.get("/v1/notifications/preferences", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    # muda a mesma preferencia de novo: upsert, nao duplica
    await client.put(
        "/v1/notifications/preferences",
        headers=headers,
        json={"topic": "TenderUpdated", "channel": "web_push", "enabled": True},
    )
    listing_after = await client.get("/v1/notifications/preferences", headers=headers)
    assert len(listing_after.json()) == 1
    assert listing_after.json()[0]["enabled"] is True


async def test_create_and_delete_push_subscription(client: httpx.AsyncClient) -> None:
    token, _ = await _signup(client, "notif-push-api")
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/v1/notifications/push-subscriptions",
        headers=headers,
        json={
            "endpoint": f"https://push.exemplo.com/{uuid.uuid4()}",
            "p256dh_key": "fake-p256dh",
            "auth_key": "fake-auth",
        },
    )
    assert create.status_code == 201, create.text
    subscription_id = create.json()["id"]

    delete = await client.delete(
        f"/v1/notifications/push-subscriptions/{subscription_id}", headers=headers
    )
    assert delete.status_code == 204

    delete_again = await client.delete(
        f"/v1/notifications/push-subscriptions/{subscription_id}", headers=headers
    )
    assert delete_again.status_code == 404


async def test_inbox_lists_alerts_with_delivery_status(client: httpx.AsyncClient) -> None:
    token, tenant_id = await _signup(client, "notif-inbox-api")
    headers = {"Authorization": f"Bearer {token}"}

    async with system_session() as session:
        await publish_event(
            session,
            topic="OpportunityMatched",
            payload={"opportunity_id": "opp-inbox", "tender_id": "tender-inbox"},
            tenant_id=tenant_id,
        )
    await dispatch_pending_events()
    await consume_notification_events_job({})

    response = await client.get("/v1/notifications", headers=headers)
    assert response.status_code == 200
    alerts = response.json()
    assert len(alerts) == 1
    assert alerts[0]["topic"] == "OpportunityMatched"
    assert len(alerts[0]["deliveries"]) == 2  # email + web_push
    assert all(d["status"] == "sent" for d in alerts[0]["deliveries"])
