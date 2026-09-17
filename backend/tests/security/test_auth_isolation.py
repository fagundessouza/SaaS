"""Isolamento de tenant para as tabelas introduzidas na Fase 2 (users, company_profiles) — mesmo
principio de tests/security/test_tenant_isolation.py, aplicado aqui as tabelas novas. RefreshToken
e EmailIndex ficam de fora de proposito (sao GLOBAL, ver core/auth/models.py e ADR-0011): sua
seguranca vem de o valor ser um segredo improvavel de adivinhar, nao de RLS.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
from sqlalchemy import select

from api.main import app
from core.auth.service import create_tenant_with_owner
from core.db.session import tenant_session
from core.tenancy.context import tenant_scope
from domains.procurement.companies.models import CompanyProfile
from domains.procurement.companies.service import new_company_profile
from tests.conftest import unique_email


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_company_profile_of_one_tenant_is_invisible_to_another() -> None:
    owner_a = await create_tenant_with_owner(
        company_name="Tenant A", email=unique_email("isola-a"), password="senha-forte-123"
    )
    owner_b = await create_tenant_with_owner(
        company_name="Tenant B", email=unique_email("isola-b"), password="senha-forte-123"
    )

    with tenant_scope(owner_a.tenant_id):
        async with tenant_session() as session:
            session.add(
                new_company_profile(tenant_id=owner_a.tenant_id, legal_name="Tenant A", cnpj=None)
            )

    with tenant_scope(owner_b.tenant_id):
        async with tenant_session() as session:
            result = await session.execute(select(CompanyProfile))
            rows = result.scalars().all()
            assert all(row.tenant_id == owner_b.tenant_id for row in rows)


async def test_api_tokens_never_expose_other_tenants_data(client: httpx.AsyncClient) -> None:
    """Fim a fim via API: o access token de um tenant nunca consegue ver o
    CompanyProfile/usuarios de outro, mesmo sabendo que eles existem."""
    signup_a = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "API Isolamento A",
            "email": unique_email("api-isola-a"),
            "password": "senha-forte-123",
        },
    )
    signup_b = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "API Isolamento B",
            "email": unique_email("api-isola-b"),
            "password": "senha-forte-123",
        },
    )

    token_a = signup_a.json()["access_token"]
    token_b = signup_b.json()["access_token"]

    profile_a = await client.get(
        "/v1/company-profile", headers={"Authorization": f"Bearer {token_a}"}
    )
    profile_b = await client.get(
        "/v1/company-profile", headers={"Authorization": f"Bearer {token_b}"}
    )

    assert profile_a.json()["legal_name"] == "API Isolamento A"
    assert profile_b.json()["legal_name"] == "API Isolamento B"
    assert profile_a.json()["id"] != profile_b.json()["id"]

    # token de B tentando ler /v1/tenants/me nunca pode devolver o tenant de A
    tenant_via_b = await client.get(
        "/v1/tenants/me", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert tenant_via_b.json()["id"] == signup_b.json()["tenant_id"]
    assert tenant_via_b.json()["id"] != signup_a.json()["tenant_id"]
