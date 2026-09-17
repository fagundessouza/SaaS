"""Worker Arq: define os jobs assincronos e o loop de despacho do outbox.

Rodar com: `uv run arq core.jobs.worker.WorkerSettings`

`process_echo_job` e o job de referencia end-to-end da Fase 1 (ver
docs/IMPLEMENTATION_ROADMAP.md): recebe um job_run_id + tenant_id, atualiza o JobRun por todo o
ciclo de vida (PENDING -> RUNNING -> COMPLETED/FAILED), publica um evento de dominio via outbox,
e registra metricas. Jobs de dominio futuros (ingestao, analise) seguem o mesmo padrao.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from arq import cron
from arq.connections import RedisSettings

from core.config import get_settings
from core.db import registry  # noqa: F401 — garante que todo model esteja registrado no Base
from core.db.session import tenant_session
from core.events.dispatcher import dispatch_pending_events
from core.events.publisher import publish_event
from core.jobs.models import JobRun, JobStatus
from core.observability.logging import configure_logging, get_logger
from core.observability.metrics import job_duration_seconds, jobs_processed_total
from core.tenancy.context import tenant_scope

logger = get_logger(__name__)


async def process_echo_job(ctx: dict[str, Any], job_run_id: str, tenant_id: str) -> None:
    started_at = time.monotonic()
    status = JobStatus.FAILED

    with tenant_scope(UUID(tenant_id)):
        async with tenant_session() as session:
            job_run = await session.get(JobRun, UUID(job_run_id))
            if job_run is None:
                logger.warning("job.not_found", job_run_id=job_run_id)
                return

            job_run.status = JobStatus.RUNNING
            await session.flush()

        async with tenant_session() as session:
            job_run = await session.get(JobRun, UUID(job_run_id))
            assert job_run is not None
            try:
                echoed = {"echo": job_run.payload.get("message"), "tenant_id": tenant_id}
                job_run.status = JobStatus.COMPLETED
                job_run.result = echoed
                status = JobStatus.COMPLETED
                await publish_event(
                    session,
                    topic="EchoJobCompleted",
                    payload={"job_run_id": job_run_id, "result": echoed},
                    tenant_id=UUID(tenant_id),
                )
            except Exception as exc:  # noqa: BLE001 — job de exemplo: qualquer falha vira FAILED
                job_run.status = JobStatus.FAILED
                job_run.error = str(exc)
                logger.error("job.failed", job_run_id=job_run_id, error=str(exc))

    duration = time.monotonic() - started_at
    job_duration_seconds.labels(job_type="echo").observe(duration)
    jobs_processed_total.labels(job_type="echo", status=status.value).inc()


async def dispatch_outbox_job(ctx: dict[str, Any]) -> None:
    await dispatch_pending_events()


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    logger.info("worker.startup")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker.shutdown")


class WorkerSettings:
    functions = [process_echo_job, dispatch_outbox_job]
    cron_jobs = [cron(dispatch_outbox_job, second={0, 10, 20, 30, 40, 50})]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
