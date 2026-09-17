"""Fluxo completo de autenticacao contra Postgres/Redis reais: signup -> login -> acesso a
endpoint protegido -> refresh (com rotacao) -> logout. Ver core/auth/service.py e
api/onboarding.py.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest

from api.main import app
from tests.conftest import unique_email


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def test_signup_creates_tenant_user_subscription_and_company_profile(
    client: httpx.AsyncClient,
) -> None:
    email = unique_email("dono")
    response = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "Fornecedora Exemplo LTDA",
            "email": email,
            "password": "senha-forte-123",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"]
    assert body["user_id"]
    assert body["company_profile_id"]
    assert body["access_token"]
    assert body["refresh_token"]

    me = await client.get("/v1/users/me", headers=_auth_header(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == email
    assert me.json()["role"] == "owner"

    tenant = await client.get("/v1/tenants/me", headers=_auth_header(body["access_token"]))
    assert tenant.status_code == 200
    assert tenant.json()["id"] == body["tenant_id"]

    profile = await client.get("/v1/company-profile", headers=_auth_header(body["access_token"]))
    assert profile.status_code == 200
    assert profile.json()["legal_name"] == "Fornecedora Exemplo LTDA"
    assert profile.json()["enrichment_status"] == "not_attempted"  # sem cnpj no signup


async def test_signup_with_duplicate_email_returns_409(client: httpx.AsyncClient) -> None:
    payload = {
        "company_name": "Empresa X",
        "email": unique_email("duplicado"),
        "password": "senha-forte-123",
    }
    first = await client.post("/v1/auth/signup", json=payload)
    assert first.status_code == 201

    second = await client.post("/v1/auth/signup", json=payload)
    assert second.status_code == 409


async def test_login_with_wrong_password_returns_401(client: httpx.AsyncClient) -> None:
    email = unique_email("login")
    await client.post(
        "/v1/auth/signup",
        json={"company_name": "Empresa Y", "email": email, "password": "senha-correta-123"},
    )

    response = await client.post(
        "/v1/auth/login", json={"email": email, "password": "senha-errada"}
    )
    assert response.status_code == 401


async def test_login_success_issues_working_token(client: httpx.AsyncClient) -> None:
    email = unique_email("login2")
    await client.post(
        "/v1/auth/signup",
        json={"company_name": "Empresa Z", "email": email, "password": "senha-correta-123"},
    )

    login_response = await client.post(
        "/v1/auth/login", json={"email": email, "password": "senha-correta-123"}
    )
    assert login_response.status_code == 200
    tokens = login_response.json()

    me = await client.get("/v1/users/me", headers=_auth_header(tokens["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == email


async def test_protected_endpoint_without_token_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/users/me")
    assert response.status_code == 401  # HTTPBearer sem credenciais


async def test_protected_endpoint_with_garbage_token_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/users/me", headers=_auth_header("token-invalido"))
    assert response.status_code == 401


async def test_refresh_rotates_token_and_old_refresh_token_is_rejected(
    client: httpx.AsyncClient,
) -> None:
    signup = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "Empresa Refresh",
            "email": unique_email("refresh"),
            "password": "senha-forte-123",
        },
    )
    original_refresh = signup.json()["refresh_token"]

    refreshed = await client.post("/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    assert new_tokens["refresh_token"] != original_refresh

    reuse_attempt = await client.post(
        "/v1/auth/refresh", json={"refresh_token": original_refresh}
    )
    assert reuse_attempt.status_code == 401

    still_works = await client.get(
        "/v1/users/me", headers=_auth_header(new_tokens["access_token"])
    )
    assert still_works.status_code == 200


async def test_logout_revokes_refresh_token(client: httpx.AsyncClient) -> None:
    signup = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "Empresa Logout",
            "email": unique_email("logout"),
            "password": "senha-forte-123",
        },
    )
    refresh_token = signup.json()["refresh_token"]

    logout_response = await client.post("/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout_response.status_code == 204

    refresh_after_logout = await client.post(
        "/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_after_logout.status_code == 401
