"""RBAC (owner/admin podem convidar, member nao) e enforcement do limite de usuarios do plano
trial (max_users=3, ver seed em alembic/versions/1fa047318986_...). Ver core/billing/service.py.
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


async def _signup(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/v1/auth/signup",
        json={"company_name": "Empresa RBAC", "email": email, "password": "senha-forte-123"},
    )
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


async def test_owner_can_invite_user_within_limit(client: httpx.AsyncClient) -> None:
    owner = await _signup(client, unique_email("owner-rbac"))

    response = await client.post(
        "/v1/users",
        json={"email": unique_email("membro1"), "password": "senha-forte-123", "role": "member"},
        headers=_auth_header(owner["access_token"]),
    )
    assert response.status_code == 201
    assert response.json()["role"] == "member"


async def test_member_cannot_invite_user(client: httpx.AsyncClient) -> None:
    owner = await _signup(client, unique_email("owner-rbac2"))
    member_email = unique_email("membro2")

    invite = await client.post(
        "/v1/users",
        json={"email": member_email, "password": "senha-forte-123", "role": "member"},
        headers=_auth_header(owner["access_token"]),
    )
    member_login = await client.post(
        "/v1/auth/login", json={"email": member_email, "password": "senha-forte-123"}
    )
    member_token = member_login.json()["access_token"]

    forbidden = await client.post(
        "/v1/users",
        json={"email": unique_email("membro3"), "password": "senha-forte-123", "role": "member"},
        headers=_auth_header(member_token),
    )
    assert invite.status_code == 201
    assert forbidden.status_code == 403


async def test_inviting_beyond_plan_limit_is_rejected(client: httpx.AsyncClient) -> None:
    owner = await _signup(client, unique_email("owner-limite"))
    header = _auth_header(owner["access_token"])

    # plano trial: max_users=3. O owner ja conta como 1 usuario.
    second = await client.post(
        "/v1/users",
        json={"email": unique_email("limite2"), "password": "senha-forte-123", "role": "member"},
        headers=header,
    )
    third = await client.post(
        "/v1/users",
        json={"email": unique_email("limite3"), "password": "senha-forte-123", "role": "member"},
        headers=header,
    )
    fourth = await client.post(
        "/v1/users",
        json={"email": unique_email("limite4"), "password": "senha-forte-123", "role": "member"},
        headers=header,
    )

    assert second.status_code == 201
    assert third.status_code == 201
    assert fourth.status_code == 403
