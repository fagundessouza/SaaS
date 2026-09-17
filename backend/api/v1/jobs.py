"""Endpoint de exemplo do fluxo ASYNC (ver ADR-0008): dispara um job e retorna 202 imediatamente;
o resultado e consultado depois via GET, nunca aguardado em linha.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.deps import require_tenant
from core.db.session import tenant_session
from core.jobs.enqueue import get_arq_pool
from core.jobs.models import JobRun, JobStatus

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


class EnqueueEchoJobRequest(BaseModel):
    message: str


class JobRunResponse(BaseModel):
    id: UUID
    job_type: str
    status: JobStatus
    result: dict[str, Any] | None = None
    error: str | None = None

    model_config = {"from_attributes": True}


@router.post("/echo", response_model=JobRunResponse, status_code=202)
async def enqueue_echo_job(
    payload: EnqueueEchoJobRequest, tenant_id: UUID = Depends(require_tenant)
) -> JobRun:
    async with tenant_session() as session:
        job_run = JobRun(
            tenant_id=tenant_id,
            job_type="echo",
            status=JobStatus.PENDING,
            payload={"message": payload.message},
        )
        session.add(job_run)
        await session.flush()
        await session.refresh(job_run)
        job_run_id = job_run.id

    pool = await get_arq_pool()
    await pool.enqueue_job("process_echo_job", str(job_run_id), str(tenant_id))

    return job_run


@router.get("/{job_id}", response_model=JobRunResponse)
async def get_job(job_id: UUID, tenant_id: UUID = Depends(require_tenant)) -> JobRun:
    async with tenant_session() as session:
        result = await session.execute(select(JobRun).where(JobRun.id == job_id))
        job_run = result.scalar_one_or_none()
        if job_run is None:
            # Por causa do RLS, isto tambem cobre o caso de job_id existir mas pertencer a
            # outro tenant — a query nem enxerga a linha, entao o retorno correto e 404, nunca 403
            # (nao vazamos nem a existencia do recurso de outro tenant).
            raise HTTPException(status_code=404, detail="Job nao encontrado")
        return job_run
