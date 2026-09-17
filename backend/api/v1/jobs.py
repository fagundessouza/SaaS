"""Consulta de status de jobs assincronos (ver ADR-0008) — generico, usado hoje pelo
enriquecimento de CompanyProfile (ver domains/procurement/companies/jobs.py).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.deps import CurrentUser, get_current_user
from core.db.session import tenant_session
from core.jobs.models import JobRun, JobStatus

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


class JobRunResponse(BaseModel):
    id: UUID
    job_type: str
    status: JobStatus
    result: dict[str, Any] | None = None
    error: str | None = None

    model_config = {"from_attributes": True}


@router.get("/{job_id}", response_model=JobRunResponse)
async def get_job(job_id: UUID, current_user: CurrentUser = Depends(get_current_user)) -> JobRun:
    async with tenant_session() as session:
        result = await session.execute(select(JobRun).where(JobRun.id == job_id))
        job_run = result.scalar_one_or_none()
        if job_run is None:
            # Por causa do RLS, isto tambem cobre o caso de job_id existir mas pertencer a
            # outro tenant — a query nem enxerga a linha, entao o retorno correto e 404, nunca 403
            # (nao vazamos nem a existencia do recurso de outro tenant).
            raise HTTPException(status_code=404, detail="Job nao encontrado")
        return job_run
