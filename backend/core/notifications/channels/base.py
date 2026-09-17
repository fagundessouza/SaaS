"""Interface de canal de notificacao — o core do Notification Engine nunca importa um SDK de
canal especifico diretamente (ver docstring de core/notifications/models.py e
EVENT_AND_NOTIFICATION_ARCHITECTURE.md: "cada canal e um adapter isolado, com suas proprias
credenciais, rate limits e formato de mensagem")."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.notifications.models import DeliveryStatus


@dataclass(frozen=True)
class NotificationContext:
    """O que um canal precisa para montar e enviar uma mensagem — nunca o ORM model `Alert`
    diretamente, para manter os adapters desacoplados do schema de banco."""

    user_email: str
    topic: str
    payload: dict[str, object]
    # Assinaturas de Web Push do usuario (vazio para outros canais) — ver PushSubscription.
    push_subscriptions: tuple[tuple[str, str, str], ...] = ()  # (endpoint, p256dh, auth)


@dataclass(frozen=True)
class DeliveryResult:
    status: DeliveryStatus
    error: str | None = None


class NotificationChannel(Protocol):
    async def send(self, context: NotificationContext) -> DeliveryResult: ...
