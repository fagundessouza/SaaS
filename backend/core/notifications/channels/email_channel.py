"""Canal de e-mail. Duas implementacoes do mesmo `NotificationChannel` — `get_email_channel()`
escolhe entre elas por configuracao (ver core/config.py), nunca por um `if` espalhado pelo
codigo que usa o canal.

`ConsoleEmailChannel` NAO e um stub/mock: e a implementacao usada em qualquer ambiente sem SMTP
configurado (todo ambiente de dev/teste deste projeto, ate hoje) — mesmo raciocinio ja aplicado a
`core/billing` ("sem gateway de pagamento"). Loga a mensagem que teria sido enviada e retorna
`SENT`, nunca `FAILED`: a ausencia de configuracao de SMTP nao e uma falha de entrega, e uma
decisao de ambiente.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from functools import lru_cache

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


class ConsoleEmailChannel:
    async def send(self, context: NotificationContext) -> DeliveryResult:
        subject, body = format_message(context.topic, context.payload)
        logger.info(
            "notification.email.console",
            to=context.user_email,
            subject=subject,
            body=body,
        )
        return DeliveryResult(status=DeliveryStatus.SENT)


class SmtpEmailChannel:
    """Envia de verdade via SMTP (`smtplib`, stdlib — sincrono, rodado em thread separada via
    `asyncio.to_thread` para nao bloquear o event loop, mesmo padrao ja usado em
    ai_platform/embeddings/fastembed_provider.py para o modelo ONNX). Falha de rede/autenticacao
    vira `DeliveryStatus.FAILED` com a mensagem de erro — nunca propagada como excecao para o
    chamador (mesma disciplina defensiva ja aplicada a outros canais/integracoes externas do
    projeto: um provedor externo instavel nunca derruba o consumidor de eventos)."""

    def __init__(
        self, *, host: str, port: int, username: str | None, password: str | None, from_email: str
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email

    async def send(self, context: NotificationContext) -> DeliveryResult:
        return await asyncio.to_thread(self._send_sync, context)

    def _send_sync(self, context: NotificationContext) -> DeliveryResult:
        subject, body = format_message(context.topic, context.payload)
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._from_email
        message["To"] = context.user_email
        message.set_content(body)

        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as server:
                server.starttls(context=ssl.create_default_context())
                if self._username and self._password:
                    server.login(self._username, self._password)
                server.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("notification.email.smtp_failed", to=context.user_email, error=str(exc))
            return DeliveryResult(status=DeliveryStatus.FAILED, error=str(exc))

        return DeliveryResult(status=DeliveryStatus.SENT)


@lru_cache
def get_email_channel() -> NotificationChannel:
    settings = get_settings()
    if not settings.smtp_host:
        return ConsoleEmailChannel()
    return SmtpEmailChannel(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_email=settings.smtp_from_email,
    )
