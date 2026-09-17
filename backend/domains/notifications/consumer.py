"""Consumidor do Redis Stream do outbox (ver core/events/dispatcher.py) para o Notification
Engine. Usa Consumer Group (`XREADGROUP`) para que cada mensagem seja confirmada (`XACK`)
somente apos o handler correspondente rodar com sucesso — se o processo cair no meio, a mensagem
nao confirmada e reentregue no proximo ciclo (mesma garantia "pelo menos uma vez" do outbox em
si). A idempotencia real mora em `Alert` (constraint `(source_event_id, user_id)`, ver
core/notifications/models.py) — reprocessar a mesma mensagem nunca duplica notificacao.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from redis.exceptions import ResponseError

from core.cache.redis_client import get_redis
from core.events.dispatcher import STREAM_NAME
from core.observability.logging import get_logger
from core.observability.metrics import notification_events_processed_total
from domains.notifications.handlers import HANDLERS

logger = get_logger(__name__)

GROUP_NAME = "notification_engine"
CONSUMER_NAME = "notification_engine-worker"
_BATCH_SIZE = 100


async def _ensure_consumer_group() -> None:
    redis = get_redis()
    try:
        await redis.xgroup_create(STREAM_NAME, GROUP_NAME, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def consume_notification_events_job(ctx: dict[str, Any]) -> dict[str, int]:
    await _ensure_consumer_group()
    redis = get_redis()

    response = await redis.xreadgroup(
        GROUP_NAME, CONSUMER_NAME, {STREAM_NAME: ">"}, count=_BATCH_SIZE
    )

    counts = {"processed": 0, "skipped": 0}
    if not response:
        return counts

    for _stream_name, messages in response:
        for message_id, fields in messages:
            topic = fields["topic"]
            handler = HANDLERS.get(topic)

            if handler is not None:
                tenant_id = uuid.UUID(fields["tenant_id"]) if fields["tenant_id"] else None
                payload = json.loads(fields["payload"])
                event_id = uuid.UUID(fields["event_id"])

                try:
                    await handler(tenant_id, payload, event_id)
                except Exception as exc:  # noqa: BLE001 — falha de um evento nao pode travar o stream
                    logger.error(
                        "notification.handler_failed",
                        topic=topic,
                        event_id=str(event_id),
                        error=str(exc),
                    )
                    # Nao confirma (XACK) — reentregue no proximo ciclo, mesma garantia do outbox.
                    continue

                counts["processed"] += 1
                notification_events_processed_total.labels(topic=topic).inc()
            else:
                counts["skipped"] += 1

            await redis.xack(STREAM_NAME, GROUP_NAME, message_id)

    logger.info("notification_engine.consumed", **counts)
    return counts
