"""CRUD de NotificationPreference do usuario corrente (Fase 10)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from core.db.session import tenant_session
from core.notifications.models import NotificationChannelType, NotificationPreference


async def set_preference(
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    topic: str,
    channel: NotificationChannelType,
    enabled: bool,
) -> NotificationPreference:
    """Upsert por `(user_id, topic, channel)` — o usuario muda a mesma preferencia repetidamente
    (ligar/desligar), nunca acumula linhas duplicadas para o mesmo topico/canal. Mesmo padrao ja
    usado em domains/procurement/tenders/items_service.py::store_tender_items."""
    async with tenant_session() as session:
        result = await session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.topic == topic,
                NotificationPreference.channel == channel,
            )
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            preference = NotificationPreference(
                tenant_id=tenant_id,
                user_id=user_id,
                topic=topic,
                channel=channel,
                enabled=enabled,
            )
            session.add(preference)
            await session.flush()
            return preference

        existing.enabled = enabled
        await session.flush()
        return existing


async def list_preferences(*, user_id: uuid.UUID) -> list[NotificationPreference]:
    async with tenant_session() as session:
        result = await session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        return list(result.scalars().all())
