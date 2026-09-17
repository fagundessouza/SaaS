"""Teste de integracao da API contra Postgres/Redis/MinIO reais (docker-compose de
desenvolvimento). Usa ASGITransport para rodar a app FastAPI em processo, sem precisar de um
servidor uvicorn de pe.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest

from api.main import app


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_healthz(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_create_tenant_and_read_self(client: httpx.AsyncClient) -> None:
    create_response = await client.post("/v1/tenants", json={"name": "Empresa de Teste"})
    assert create_response.status_code == 201
    tenant = create_response.json()
    assert tenant["name"] == "Empresa de Teste"
    assert tenant["status"] == "trial"

    me_response = await client.get(
        "/v1/tenants/me", headers={"X-Tenant-Id": tenant["id"]}
    )
    assert me_response.status_code == 200
    assert me_response.json()["id"] == tenant["id"]


async def test_get_tenant_me_without_header_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/tenants/me")
    assert response.status_code == 422  # header obrigatorio ausente


async def test_get_tenant_me_with_unknown_tenant_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/v1/tenants/me", headers={"X-Tenant-Id": "00000000-0000-0000-0000-000000000000"}
    )
    assert response.status_code == 404


async def test_enqueue_job_requires_tenant_and_returns_202(client: httpx.AsyncClient) -> None:
    create_response = await client.post("/v1/tenants", json={"name": "Empresa Job"})
    tenant_id = create_response.json()["id"]

    job_response = await client.post(
        "/v1/jobs/echo",
        json={"message": "ola"},
        headers={"X-Tenant-Id": tenant_id},
    )
    assert job_response.status_code == 202
    job = job_response.json()
    assert job["status"] == "pending"

    other_tenant = (
        await client.post("/v1/tenants", json={"name": "Empresa Job Outra"})
    ).json()["id"]
    cross_read = await client.get(
        f"/v1/jobs/{job['id']}", headers={"X-Tenant-Id": other_tenant}
    )
    assert cross_read.status_code == 404
