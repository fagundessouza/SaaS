"""Alert / Notification / NotificationPreference / PushSubscription — Notification Engine
(Fase 10, ver docs/EVENT_AND_NOTIFICATION_ARCHITECTURE.md).

Fica em `core/` (nao `domains/`) porque e infraestrutura reutilizavel por qualquer produtor de
evento de dominio — mesmo raciocinio ja aplicado a `core/billing` (Plan/Subscription sao
conceitos de SaaS genericos, nao logica de negocio de licitacao). A logica que DECIDE quais
tenants/usuarios um evento afeta (ex.: "quem tem Opportunity para este Tender retificado?") vive
em `domains/notifications/` — precisa ler `Opportunity`/`CompanyProfile`, o que `core` nao pode
fazer (contrato de camadas, ver ADR-0001).

`Alert` e a decisao "isto aconteceu e importa para este usuario"; `Notification` e uma tentativa
concreta de entrega por um canal. Um `Alert` pode gerar N `Notification` (uma por canal
habilitado nas preferencias do usuario) — falha em um canal nao impede tentativa em outro (ver
docstring do modulo de arquitetura).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, IdMixin, TenantScopedMixin, TimestampMixin


class NotificationChannelType(enum.StrEnum):
    EMAIL = "email"
    WEB_PUSH = "web_push"
    # WhatsApp/Telegram deliberadamente fora do escopo minimo desta fase (ver
    # IMPLEMENTATION_ROADMAP.md: "WhatsApp entra quando houver validacao de custo/demanda, BSP
    # tem custo por conversa") — nao adicionados aqui especulativamente.


class DeliveryStatus(enum.StrEnum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"


class NotificationPreference(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    """Preferencia de canal por usuario e por topico de evento (ex.: "TenderUpdated" via email,
    "OpportunityMatched" via web_push) — nunca uma preferencia global unica (ver docstring da
    arquitetura). Ausencia de linha para um (user_id, topic, channel) = comportamento default do
    canal (ver `core/notifications/service.py::_is_channel_enabled`), nao "desabilitado"."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "topic", "channel", name="uq_notification_preferences_user_topic_channel"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    channel: Mapped[NotificationChannelType] = mapped_column(
        Enum(NotificationChannelType, name="notification_channel_type"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(nullable=False)


class PushSubscription(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    """Assinatura de Web Push (RFC 8292) de um navegador do usuario — criada pelo frontend via
    `PushManager.subscribe()` (Fase 11, ainda nao existe); a tabela ja nasce correta para quando
    houver um frontend registrando assinaturas reais. Sem assinatura cadastrada, o canal
    `web_push` simplesmente nao tem para onde entregar (ver `WebPushChannel.send`)."""

    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh_key: Mapped[str] = mapped_column(Text, nullable=False)
    auth_key: Mapped[str] = mapped_column(Text, nullable=False)


class Alert(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    """Decisao de que um evento de dominio importa para um usuario especifico. `source_event_id`
    e o `DomainEvent.id` (outbox, GLOBAL) que originou este Alert — a unicidade
    (source_event_id, user_id) e a idempotencia exigida pela arquitetura de eventos ("todo
    consumidor mantem registro de event_id processados e descarta reentregas", ver
    EVENT_AND_NOTIFICATION_ARCHITECTURE.md): reprocessar o mesmo evento do Redis Stream (entrega
    "pelo menos uma vez") nunca duplica o Alert do mesmo usuario."""

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("source_event_id", "user_id", name="uq_alerts_event_user"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    # dado estruturado do evento + contexto legivel (ex.: {"tender_id": ..., "objeto": ...,
    # "summary": "Edital X foi retificado"}) — gerado deterministicamente pelo handler de
    # dominio, nunca por um LLM (ai_platform/llm nao existe ainda, Fase 9).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class Notification(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    """Uma tentativa concreta de entrega de um Alert por um canal. `PENDING -> SENT -> DELIVERED
    | FAILED | BOUNCED` (ver docstring da arquitetura) — `DELIVERED`/`BOUNCED` exigem webhook de
    confirmacao do provedor (fora do escopo minimo desta fase: os canais implementados marcam
    `SENT` ou `FAILED` na hora, nunca `DELIVERED`/`BOUNCED` sem um provedor real confirmando)."""

    __tablename__ = "notifications"

    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id"), nullable=False, index=True
    )
    channel: Mapped[NotificationChannelType] = mapped_column(
        Enum(NotificationChannelType, name="notification_channel_type"), nullable=False
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status"), nullable=False, default=DeliveryStatus.PENDING
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
