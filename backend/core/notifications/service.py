"""Dispatch de Alert -> Notification por canal. `create_alert_and_dispatch` e a unica porta de
entrada usada por `domains/notifications/` (ver docstring de core/notifications/models.py sobre
a divisao entre "core" generico e "domains" com conhecimento cross-domain).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.auth.models import User
from core.db.session import tenant_session
from core.notifications.channels.base import NotificationChannel, NotificationContext
from core.notifications.channels.email_channel import get_email_channel
from core.notifications.channels.web_push_channel import get_web_push_channel
from core.notifications.models import (
    Alert,
    DeliveryStatus,
    Notification,
    NotificationChannelType,
    NotificationPreference,
    PushSubscription,
)
from core.observability.logging import get_logger
from core.observability.metrics import (
    alerts_created_total,
    notifications_sent_total,
)

logger = get_logger(__name__)

# Canal habilitado por padrao quando o usuario nunca configurou preferencia — modelo opt-out,
# comum em SaaS (o usuario recebe por padrao, desabilita se quiser). Ver NotificationPreference.
_DEFAULT_CHANNEL_ENABLED = True


async def _is_channel_enabled(
    user_id: uuid.UUID, topic: str, channel: NotificationChannelType
) -> bool:
    async with tenant_session() as session:
        result = await session.execute(
            select(NotificationPreference.enabled).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.topic == topic,
                NotificationPreference.channel == channel,
            )
        )
        enabled = result.scalar_one_or_none()
        return _DEFAULT_CHANNEL_ENABLED if enabled is None else enabled


async def _push_subscriptions(user_id: uuid.UUID) -> tuple[tuple[str, str, str], ...]:
    async with tenant_session() as session:
        result = await session.execute(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        )
        return tuple(
            (sub.endpoint, sub.p256dh_key, sub.auth_key) for sub in result.scalars().all()
        )


async def create_alert_and_dispatch(
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    topic: str,
    payload: dict[str, object],
    source_event_id: uuid.UUID,
) -> uuid.UUID | None:
    """Cria o Alert (idempotente por `(source_event_id, user_id)`, ver models.py) e dispara a
    entrega em todo canal habilitado para este usuario/topico. Retorna `None` quando o Alert ja
    existia (reentrega do outbox, ver EVENT_AND_NOTIFICATION_ARCHITECTURE.md) — nada e reenviado.
    """
    async with tenant_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            logger.error("notification.user_not_found", user_id=str(user_id))
            return None

        try:
            alert = Alert(
                tenant_id=tenant_id,
                user_id=user_id,
                topic=topic,
                payload=payload,
                source_event_id=source_event_id,
            )
            session.add(alert)
            await session.flush()
        except IntegrityError:
            logger.info(
                "notification.alert_already_exists",
                source_event_id=str(source_event_id),
                user_id=str(user_id),
            )
            return None

        alert_id = alert.id
        user_email = user.email

    alerts_created_total.labels(topic=topic).inc()

    subscriptions = await _push_subscriptions(user_id)
    channels: dict[NotificationChannelType, NotificationChannel] = {
        NotificationChannelType.EMAIL: get_email_channel(),
        NotificationChannelType.WEB_PUSH: get_web_push_channel(),
    }

    for channel_type, channel in channels.items():
        if not await _is_channel_enabled(user_id, topic, channel_type):
            continue

        async with tenant_session() as session:
            notification = Notification(
                tenant_id=tenant_id,
                alert_id=alert_id,
                channel=channel_type,
                status=DeliveryStatus.PENDING,
            )
            session.add(notification)
            await session.flush()
            notification_id = notification.id

        context = NotificationContext(
            user_email=user_email,
            topic=topic,
            payload=payload,
            push_subscriptions=subscriptions,
        )
        result = await channel.send(context)

        async with tenant_session() as session:
            persisted = await session.get(Notification, notification_id)
            assert persisted is not None
            persisted.status = result.status
            persisted.error = result.error
            persisted.sent_at = (
                datetime.now(UTC) if result.status == DeliveryStatus.SENT else None
            )

        notifications_sent_total.labels(
            channel=channel_type.value, status=result.status.value
        ).inc()

    return alert_id


async def list_alerts_for_user(
    *, user_id: uuid.UUID, limit: int = 50
) -> list[tuple[Alert, list[Notification]]]:
    """Inbox do usuario corrente: cada Alert com o resultado de entrega em cada canal tentado."""
    async with tenant_session() as session:
        alerts = list(
            (
                await session.execute(
                    select(Alert)
                    .where(Alert.user_id == user_id)
                    .order_by(Alert.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

        notifications_result = await session.execute(
            select(Notification).where(
                Notification.alert_id.in_([alert.id for alert in alerts])
            )
        )
        notifications_by_alert: dict[uuid.UUID, list[Notification]] = {}
        for notification in notifications_result.scalars().all():
            notifications_by_alert.setdefault(notification.alert_id, []).append(notification)

        return [(alert, notifications_by_alert.get(alert.id, [])) for alert in alerts]
