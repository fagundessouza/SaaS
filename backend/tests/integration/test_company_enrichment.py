"""Enriquecimento de CompanyProfile via CNPJ. A chamada HTTP externa (BrasilAPI) e mockada com
respx — o teste valida a logica de negocio (domains/procurement/companies/service.py), nao a
disponibilidade da fonte externa.

Testado no nivel de servico, nao via job assincrono completo: o worker Arq roda como processo
separado (ver worker.py) e nao esta necessariamente de pe durante `pytest` — testar a funcao de
servico diretamente (chamada pelo job, ver domains/.../jobs.py) cobre a mesma logica sem
depender de infraestrutura de processo externo ao teste.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
import respx

from api.main import app
from core.auth.service import create_tenant_with_owner
from core.billing.service import get_trial_plan, new_trial_subscription
from core.db.session import tenant_session
from core.tenancy.context import tenant_scope
from domains.procurement.companies.models import CompanyProfile, EnrichmentStatus
from domains.procurement.companies.service import enrich_company_profile, new_company_profile
from tests.conftest import unique_cnpj, unique_email

BRASIL_API_BASE = "https://brasilapi.com.br/api/cnpj/v1"

FAKE_CNPJ_RESPONSE = {
    "razao_social": "EMPRESA FICTICIA LTDA",
    "nome_fantasia": "Empresa Ficticia",
    "cnae_fiscal": 6201501,
    "cnae_fiscal_descricao": "Desenvolvimento de programas de computador sob encomenda",
    "cnaes_secundarios": [{"codigo": 6202300, "descricao": "Consultoria em TI"}],
    "municipio": "SAO PAULO",
    "uf": "SP",
}


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_tenant_with_company(cnpj: str) -> tuple[uuid.UUID, uuid.UUID]:
    owner = await create_tenant_with_owner(
        company_name="Empresa Enriquecimento",
        email=unique_email("enrich"),
        password="senha-forte-123",
    )
    with tenant_scope(owner.tenant_id):
        async with tenant_session() as session:
            plan = await get_trial_plan(session)
            session.add(new_trial_subscription(tenant_id=owner.tenant_id, plan_id=plan.id))
            profile = new_company_profile(
                tenant_id=owner.tenant_id, legal_name="Empresa Enriquecimento", cnpj=cnpj
            )
            session.add(profile)
            await session.flush()
            company_profile_id = profile.id

    return owner.tenant_id, company_profile_id


@respx.mock
async def test_enrich_company_profile_success() -> None:
    cnpj = unique_cnpj()
    respx.get(f"{BRASIL_API_BASE}/{cnpj}").mock(
        return_value=httpx.Response(200, json=FAKE_CNPJ_RESPONSE)
    )

    tenant_id, company_profile_id = await _create_tenant_with_company(cnpj)

    with tenant_scope(tenant_id):
        await enrich_company_profile(tenant_id, company_profile_id)

        async with tenant_session() as session:
            profile = await session.get(CompanyProfile, company_profile_id)
            assert profile is not None
            assert profile.enrichment_status == EnrichmentStatus.ENRICHED
            assert profile.legal_name == "EMPRESA FICTICIA LTDA"
            assert profile.trade_name == "Empresa Ficticia"
            assert profile.regions == ["SP"]
            assert len(profile.cnaes) == 2


@respx.mock
async def test_enrich_company_profile_not_found_marks_failed() -> None:
    cnpj = unique_cnpj()
    respx.get(f"{BRASIL_API_BASE}/{cnpj}").mock(return_value=httpx.Response(404))

    tenant_id, company_profile_id = await _create_tenant_with_company(cnpj)

    with tenant_scope(tenant_id):
        await enrich_company_profile(tenant_id, company_profile_id)

        async with tenant_session() as session:
            profile = await session.get(CompanyProfile, company_profile_id)
            assert profile is not None
            assert profile.enrichment_status == EnrichmentStatus.FAILED
            assert profile.enrichment_error is not None


async def test_update_cnpj_endpoint_marks_pending_and_enqueues(client: httpx.AsyncClient) -> None:
    signup = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "Empresa Update CNPJ",
            "email": unique_email("updatecnpj"),
            "password": "senha-forte-123",
        },
    )
    access_token = signup.json()["access_token"]
    cnpj = unique_cnpj()

    response = await client.put(
        "/v1/company-profile/cnpj",
        json={"cnpj": cnpj},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    assert response.json()["cnpj"] == cnpj
    assert response.json()["enrichment_status"] == "pending"
