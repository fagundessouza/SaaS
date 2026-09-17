"""Plan (catalogo, GLOBAL) e Subscription (por tenant, RLS).

Entitlement e Usage (ver docs/DOMAIN_MODEL.md) NAO viram tabela nesta fase: sem nenhum
consumidor real de limite alem de `max_users` (ver core/billing/service.py), persistir e
invalidar um cache de entitlement seria complexidade sem consumidor — os limites sao lidos
direto de `Plan.limits` via a Subscription ativa do tenant, calculados sob demanda. Se/quando
mais planos e mais dimensoes de uso existirem, revisar esta decisao (seção 30 do prompt mestre:
nao adicionar componente sem justificativa).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, IdMixin, TenantScopedMixin, TimestampMixin


class SubscriptionStatus(enum.StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class Plan(IdMixin, TimestampMixin, Base):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Subscription(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status"),
        nullable=False,
        default=SubscriptionStatus.TRIALING,
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
