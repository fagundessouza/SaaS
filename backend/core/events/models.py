"""DomainEvent — tabela de outbox transacional (ver docs/EVENT_AND_NOTIFICATION_ARCHITECTURE.md).

Nota de design: esta tabela NAO tem RLS habilitado. Ela e uma estrutura interna de
infraestrutura, despachada por um worker de confianca (core/events/dispatcher.py) que
precisa enxergar eventos de todos os tenants para roteá-los — nunca e exposta diretamente a uma
rota de API tenant-scoped. O isolamento de tenant se aplica no momento em que um *consumidor*
de evento le o payload e busca dado adicional (esse sim, via tenant_session normalmente).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, IdMixin, TimestampMixin


class DomainEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "domain_events"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    topic: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
