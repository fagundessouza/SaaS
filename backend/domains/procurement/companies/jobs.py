"""Job assincrono de enriquecimento de CompanyProfile — segue o mesmo padrao de rastreamento
via JobRun estabelecido na Fase 1 (ver core/jobs/models.py e docs/IMPLEMENTATION_ROADMAP.md).
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from core.db.session import tenant_session
from core.jobs.models import JobRun, JobStatus
from core.observability.logging import get_logger
from core.observability.metrics import job_duration_seconds, jobs_processed_total
from core.tenancy.context import tenant_scope
from domains.procurement.companies.models import CompanyProfile, EnrichmentStatus
from domains.procurement.companies.service import enrich_company_profile

logger = get_logger(__name__)

JOB_TYPE = "enrich_company_profile"


async def enrich_company_profile_job(
    ctx: dict[str, Any], job_run_id: str, tenant_id: str, company_profile_id: str
) -> None:
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

        try:
            await enrich_company_profile(UUID(tenant_id), UUID(company_profile_id))
        except Exception as exc:  # noqa: BLE001 — job worker: qualquer falha vira JobRun.FAILED
            async with tenant_session() as session:
                job_run = await session.get(JobRun, UUID(job_run_id))
                assert job_run is not None
                job_run.status = JobStatus.FAILED
                job_run.error = str(exc)
            logger.error("job.failed", job_run_id=job_run_id, error=str(exc))
        else:
            async with tenant_session() as session:
                job_run = await session.get(JobRun, UUID(job_run_id))
                assert job_run is not None
                profile = await session.get(CompanyProfile, UUID(company_profile_id))
                job_run.status = (
                    JobStatus.COMPLETED
                    if profile and profile.enrichment_status == EnrichmentStatus.ENRICHED
                    else JobStatus.FAILED
                )
                job_run.result = (
                    {"enrichment_status": profile.enrichment_status.value} if profile else None
                )
                status = job_run.status

    duration = time.monotonic() - started_at
    job_duration_seconds.labels(job_type=JOB_TYPE).observe(duration)
    jobs_processed_total.labels(job_type=JOB_TYPE, status=status.value).inc()
