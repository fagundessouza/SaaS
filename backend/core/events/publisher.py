"""Publicacao de eventos de dominio via outbox transacional.

`publish_event` apenas grava a linha na mesma sessao/transacao da mudanca de dominio que a
originou — nunca abre uma sessao propria. Isso e o que garante atomicidade entre "o estado mudou"
e "o evento existe para ser despachado" (outbox pattern, ver ADR-0004 e
docs/EVENT_AND_NOTIFICATION_ARCHITECTURE.md).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.events.models import DomainEvent


async def publish_event(
    session: AsyncSession,
    *,
    topic: str,
    payload: dict[str, Any],
    tenant_id: uuid.UUID | None,
) -> DomainEvent:
    event = DomainEvent(topic=topic, payload=payload, tenant_id=tenant_id)
    session.add(event)
    await session.flush()
    return event
