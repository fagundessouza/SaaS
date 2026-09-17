"""Testes puros dos canais 'console' (sem DB/rede) — a implementacao real usada em qualquer
ambiente sem SMTP/VAPID configurado (ver core/notifications/channels/*.py)."""

from __future__ import annotations

from core.notifications.channels.base import NotificationContext
from core.notifications.channels.email_channel import (
    ConsoleEmailChannel,
    SmtpEmailChannel,
    get_email_channel,
)
from core.notifications.channels.web_push_channel import (
    ConsolePushChannel,
    WebPushChannel,
    get_web_push_channel,
)
from core.notifications.models import DeliveryStatus


async def test_console_email_channel_returns_sent() -> None:
    channel = ConsoleEmailChannel()
    context = NotificationContext(
        user_email="user@exemplo.com", topic="TenderUpdated", payload={"tender_id": "abc"}
    )

    result = await channel.send(context)

    assert result.status == DeliveryStatus.SENT
    assert result.error is None


async def test_console_push_channel_returns_sent_without_subscriptions() -> None:
    channel = ConsolePushChannel()
    context = NotificationContext(
        user_email="user@exemplo.com", topic="OpportunityMatched", payload={}
    )

    result = await channel.send(context)

    assert result.status == DeliveryStatus.SENT


async def test_web_push_channel_returns_sent_when_no_subscriptions_to_deliver_to() -> None:
    """Sem PushSubscription cadastrada (usuario ainda nao tem frontend registrando uma, Fase
    11), o canal nao tem para onde entregar — resultado valido, nunca uma falha (ver docstring
    de core/notifications/channels/web_push_channel.py)."""
    channel = WebPushChannel(private_key="fake-key", subject="mailto:test@exemplo.com")
    context = NotificationContext(
        user_email="user@exemplo.com", topic="AnalysisCompleted", payload={}
    )

    result = await channel.send(context)

    assert result.status == DeliveryStatus.SENT


def test_get_email_channel_returns_console_when_smtp_not_configured() -> None:
    """SMTP_HOST em branco (padrao de qualquer ambiente deste projeto ate hoje, ver
    .env.example) -> ConsoleEmailChannel, nunca SmtpEmailChannel."""
    get_email_channel.cache_clear()
    channel = get_email_channel()

    assert isinstance(channel, ConsoleEmailChannel)
    assert not isinstance(channel, SmtpEmailChannel)


def test_get_web_push_channel_returns_console_when_vapid_not_configured() -> None:
    get_web_push_channel.cache_clear()
    channel = get_web_push_channel()

    assert isinstance(channel, ConsolePushChannel)
    assert not isinstance(channel, WebPushChannel)
