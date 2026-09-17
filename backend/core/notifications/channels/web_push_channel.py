"""Canal de Web Push (RFC 8292, via VAPID). Mesmo raciocinio do e-mail
(core/notifications/channels/email_channel.py): `ConsolePushChannel` e a implementacao real para
ambiente sem chaves VAPID configuradas, `WebPushChannel` envia de verdade quando ha.

Ao contrario de e-mail, Web Push nunca depende de uma conta de terceiro — so das proprias
chaves VAPID (geradas localmente, ver core/config.py) e de o usuario ter uma
`PushSubscription` cadastrada (que so existe depois que um frontend chamar
`PushManager.subscribe()`, Fase 11 — ate la, `context.push_subscriptions` sempre vem vazio e o
canal nao tem para onde entregar, o que e um resultado valido, nao uma falha)."""

from __future__ import annotations

import asyncio
import json
from functools import lru_cache

from pywebpush import WebPushException, webpush

from core.config import get_settings
from core.notifications.channels.base import (
    DeliveryResult,
    NotificationChannel,
    NotificationContext,
)
from core.notifications.formatting import format_message
from core.notifications.models import DeliveryStatus
from core.observability.logging import get_logger

logger = get_logger(__name__)


class ConsolePushChannel:
    async def send(self, context: NotificationContext) -> DeliveryResult:
        subject, body = format_message(context.topic, context.payload)
        logger.info(
            "notification.web_push.console",
            subscriptions=len(context.push_subscriptions),
            subject=subject,
            body=body,
        )
        return DeliveryResult(status=DeliveryStatus.SENT)


class WebPushChannel:
    def __init__(self, *, private_key: str, subject: str) -> None:
        self._private_key = private_key
        self._subject = subject

    async def send(self, context: NotificationContext) -> DeliveryResult:
        if not context.push_subscriptions:
            # Nenhuma assinatura cadastrada para este usuario: resultado valido (ver docstring
            # do modulo), nunca tratado como falha de entrega.
            return DeliveryResult(status=DeliveryStatus.SENT)
        return await asyncio.to_thread(self._send_sync, context)

    def _send_sync(self, context: NotificationContext) -> DeliveryResult:
        subject, body = format_message(context.topic, context.payload)
        payload = json.dumps({"title": subject, "body": body})

        errors: list[str] = []
        for endpoint, p256dh, auth in context.push_subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": endpoint,
                        "keys": {"p256dh": p256dh, "auth": auth},
                    },
                    data=payload,
                    vapid_private_key=self._private_key,
                    vapid_claims={"sub": self._subject},
                )
            except WebPushException as exc:
                errors.append(str(exc))
                logger.error("notification.web_push.failed", endpoint=endpoint, error=str(exc))

        if errors and len(errors) == len(context.push_subscriptions):
            # Todas as assinaturas falharam — nenhuma entrega aconteceu de fato.
            return DeliveryResult(status=DeliveryStatus.FAILED, error="; ".join(errors))
        return DeliveryResult(status=DeliveryStatus.SENT)


@lru_cache
def get_web_push_channel() -> NotificationChannel:
    settings = get_settings()
    if not settings.vapid_private_key:
        return ConsolePushChannel()
    return WebPushChannel(private_key=settings.vapid_private_key, subject=settings.vapid_subject)
