"""Orquestracao do signup completo — o unico lugar autorizado a compor Tenant+User (core.auth),
Subscription (core.billing) e CompanyProfile (domains.procurement.companies) numa unica operacao
de negocio, porque `api` e a unica camada que pode depender de todas as outras (ver
core/auth/service.py para a explicacao de por que isso nao vive em `core`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from core.auth.models import Role
from core.auth.service import TokenPair, create_tenant_with_owner, issue_token_pair
from core.billing.service import get_trial_plan, new_trial_subscription
from core.db.session import tenant_session
from core.jobs.enqueue import get_arq_pool
from core.jobs.models import JobRun, JobStatus
from core.tenancy.context import tenant_scope
from domains.procurement.companies.jobs import JOB_TYPE as ENRICH_COMPANY_PROFILE_JOB_TYPE
from domains.procurement.companies.service import new_company_profile


@dataclass(frozen=True)
class SignupResult:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    company_profile_id: uuid.UUID
    tokens: TokenPair


async def signup(
    *, company_name: str, email: str, password: str, cnpj: str | None
) -> SignupResult:
    owner = await create_tenant_with_owner(
        company_name=company_name, email=email, password=password
    )

    job_run_id: uuid.UUID | None = None

    with tenant_scope(owner.tenant_id):
        async with tenant_session() as session:
            plan = await get_trial_plan(session)
            session.add(new_trial_subscription(tenant_id=owner.tenant_id, plan_id=plan.id))

            profile = new_company_profile(
                tenant_id=owner.tenant_id, legal_name=company_name, cnpj=cnpj
            )
            session.add(profile)
            await session.flush()
            company_profile_id = profile.id

            if cnpj:
                job_run = JobRun(
                    tenant_id=owner.tenant_id,
                    job_type=ENRICH_COMPANY_PROFILE_JOB_TYPE,
                    status=JobStatus.PENDING,
                    payload={"company_profile_id": str(company_profile_id)},
                )
                session.add(job_run)
                await session.flush()
                job_run_id = job_run.id

    if job_run_id is not None:
        pool = await get_arq_pool()
        await pool.enqueue_job(
            "enrich_company_profile_job",
            str(job_run_id),
            str(owner.tenant_id),
            str(company_profile_id),
        )

    tokens = await issue_token_pair(
        user_id=owner.user_id, tenant_id=owner.tenant_id, role=Role.OWNER
    )

    return SignupResult(
        tenant_id=owner.tenant_id,
        user_id=owner.user_id,
        company_profile_id=company_profile_id,
        tokens=tokens,
    )
