"""CRUD de PushSubscription do usuario corrente (Fase 10) — registrada pelo frontend via
`PushManager.subscribe()` (Fase 11, ainda nao existe)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from core.db.session import tenant_session
from core.notifications.models import PushSubscription


class PushSubscriptionNotFoundError(Exception):
    pass


async def create_push_subscription(
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    endpoint: str,
    p256dh_key: str,
    auth_key: str,
) -> PushSubscription:
    async with tenant_session() as session:
        existing = await session.execute(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )
        found = existing.scalar_one_or_none()
        if found is not None:
            # Mesmo endpoint (mesmo navegador/dispositivo) reassinando — atualiza as chaves em
            # vez de violar a UniqueConstraint em `endpoint`.
            found.p256dh_key = p256dh_key
            found.auth_key = auth_key
            await session.flush()
            return found

        subscription = PushSubscription(
            tenant_id=tenant_id,
            user_id=user_id,
            endpoint=endpoint,
            p256dh_key=p256dh_key,
            auth_key=auth_key,
        )
        session.add(subscription)
        await session.flush()
        return subscription


async def delete_push_subscription(*, subscription_id: uuid.UUID) -> None:
    async with tenant_session() as session:
        subscription = await session.get(PushSubscription, subscription_id)
        if subscription is None:
            raise PushSubscriptionNotFoundError(str(subscription_id))
        await session.delete(subscription)
