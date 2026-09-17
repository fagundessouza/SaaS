"""Teste de seguranca obrigatorio (ver docs/DEVELOPMENT.md e ADR-0002): nenhum tenant pode ler
ou escrever dado de outro tenant, em nenhuma circunstancia. Roda contra Postgres real (mesma
infra do docker-compose de desenvolvimento), usando o papel `app_runtime` (nao-superusuario) —
e exatamente essa condicao que faz o Row-Level Security ser de fato aplicado (ver
ops/docker/initdb/01-app-role.sql: um superusuario ignoraria RLS e este teste passaria por
motivo errado).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

import model_registry  # noqa: F401 — garante Base.metadata completo
from core.db.session import system_session, tenant_session
from core.jobs.models import JobRun, JobStatus
from core.tenancy.context import TenantContextError, tenant_scope
from core.tenancy.models import Tenant


async def _create_tenant(name: str) -> uuid.UUID:
    async with system_session() as session:
        tenant = Tenant(name=name)
        session.add(tenant)
        await session.flush()
        return tenant.id


async def test_tenant_session_requires_active_tenant_scope() -> None:
    with pytest.raises(TenantContextError):
        async with tenant_session():
            pass


async def test_tenant_cannot_read_job_run_of_another_tenant() -> None:
    tenant_a = await _create_tenant("Isolamento A")
    tenant_b = await _create_tenant("Isolamento B")

    with tenant_scope(tenant_a):
        async with tenant_session() as session:
            job = JobRun(tenant_id=tenant_a, job_type="test", status=JobStatus.PENDING, payload={})
            session.add(job)
            await session.flush()
            job_id = job.id

    with tenant_scope(tenant_b):
        async with tenant_session() as session:
            result = await session.execute(select(JobRun).where(JobRun.id == job_id))
            assert result.scalar_one_or_none() is None

    with tenant_scope(tenant_a):
        async with tenant_session() as session:
            result = await session.execute(select(JobRun).where(JobRun.id == job_id))
            assert result.scalar_one_or_none() is not None


async def test_tenant_listing_never_includes_other_tenants_rows() -> None:
    tenant_a = await _create_tenant("Isolamento Lista A")
    tenant_b = await _create_tenant("Isolamento Lista B")

    with tenant_scope(tenant_a):
        async with tenant_session() as session:
            session.add(
                JobRun(tenant_id=tenant_a, job_type="test", status=JobStatus.PENDING, payload={})
            )

    with tenant_scope(tenant_b):
        async with tenant_session() as session:
            session.add(
                JobRun(tenant_id=tenant_b, job_type="test", status=JobStatus.PENDING, payload={})
            )

    with tenant_scope(tenant_b):
        async with tenant_session() as session:
            result = await session.execute(select(JobRun))
            rows = result.scalars().all()
            assert len(rows) >= 1
            assert all(row.tenant_id == tenant_b for row in rows)


async def test_cannot_insert_job_run_tagged_as_a_different_tenant() -> None:
    """Defesa em profundidade: mesmo se um bug de aplicacao passar o tenant_id errado, a
    politica WITH CHECK do Postgres rejeita a escrita — nao depende de o código estar certo.
    """
    tenant_a = await _create_tenant("WithCheck A")
    tenant_b = await _create_tenant("WithCheck B")

    with tenant_scope(tenant_a):
        async with tenant_session() as session:
            rogue_job = JobRun(
                tenant_id=tenant_b, job_type="test", status=JobStatus.PENDING, payload={}
            )
            session.add(rogue_job)
            with pytest.raises(DBAPIError):
                await session.flush()
