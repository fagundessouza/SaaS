"""Despacho do outbox: le DomainEvent nao despachados e publica em um Redis Stream.

Roda como job periodico (ver core/jobs/worker.py, cron `dispatch_outbox`). E um componente
interno de infraestrutura — usa system_session de proposito, porque precisa enxergar eventos de
todos os tenants para roteá-los; nunca e chamado a partir de codigo tenant-scoped.

Entrega e "pelo menos uma vez": se o processo cair entre o XADD e o marcar dispatched_at, o
evento sera reenviado na proxima rodada. Por isso todo consumidor precisa ser idempotente por
event_id (ver docs/EVENT_AND_NOTIFICATION_ARCHITECTURE.md).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update

from core.cache.redis_client import get_redis
from core.db.session import system_session
from core.events.models import DomainEvent
from core.observability.metrics import outbox_events_dispatched_total

logger = structlog.get_logger(__name__)

STREAM_NAME = "domain_events"


async def dispatch_pending_events(batch_size: int = 100) -> int:
    redis = get_redis()

    async with system_session() as session:
        result = await session.execute(
            select(DomainEvent)
            .where(DomainEvent.dispatched_at.is_(None))
            .order_by(DomainEvent.created_at)
            .limit(batch_size)
        )
        pending = list(result.scalars().all())

        if not pending:
            return 0

        for event in pending:
            await redis.xadd(
                STREAM_NAME,
                {
                    "event_id": str(event.id),
                    "tenant_id": str(event.tenant_id) if event.tenant_id else "",
                    "topic": event.topic,
                    "payload": json.dumps(event.payload),
                },
            )

        dispatched_ids = [event.id for event in pending]
        await session.execute(
            update(DomainEvent)
            .where(DomainEvent.id.in_(dispatched_ids))
            .values(dispatched_at=datetime.now(UTC))
        )

    outbox_events_dispatched_total.inc(len(pending))
    logger.info("outbox.dispatched", count=len(pending))
    return len(pending)
