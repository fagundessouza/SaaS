"""GET /v1/tenders/{id}/items e /requirements — qualquer usuario autenticado, sem escopo de
tenant (conteudo GLOBAL, ver api/v1/tenders.py)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest

from api.main import app
from core.db.session import system_session
from domains.procurement.tenders.items_service import store_tender_items
from domains.procurement.tenders.models import Tender
from ingestion.connectors.base import RawTenderItem
from tests.conftest import unique_email


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _signup(client: httpx.AsyncClient) -> str:
    signup = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "Empresa Tenders",
            "email": unique_email("tenders-api"),
            "password": "senha-forte-123",
        },
    )
    return str(signup.json()["access_token"])


async def _create_tender() -> uuid.UUID:
    async with system_session() as session:
        tender = Tender(
            source="pncp",
            external_id=f"test-api-{uuid.uuid4()}",
            orgao_cnpj="00394460000141",
            orgao_nome="Prefeitura Exemplo",
            unidade_nome=None,
            modalidade="Pregao Eletronico",
            objeto="Objeto de teste",
            valor_estimado=None,
            data_publicacao=None,
            data_abertura_proposta=None,
            data_encerramento_proposta=None,
            situacao=None,
            latest_version_number=1,
        )
        session.add(tender)
        await session.flush()
        return tender.id


async def test_get_tender_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/v1/tenders/{uuid.uuid4()}")
    assert response.status_code == 401


async def test_get_tender_returns_404_for_unknown_tender(client: httpx.AsyncClient) -> None:
    access_token = await _signup(client)

    response = await client.get(
        f"/v1/tenders/{uuid.uuid4()}", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 404


async def test_get_tender_returns_stored_fields(client: httpx.AsyncClient) -> None:
    tender_id = await _create_tender()
    access_token = await _signup(client)

    response = await client.get(
        f"/v1/tenders/{tender_id}", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(tender_id)
    assert body["orgao_nome"] == "Prefeitura Exemplo"
    assert body["modalidade"] == "Pregao Eletronico"
    assert body["objeto"] == "Objeto de teste"


async def test_list_items_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/v1/tenders/{uuid.uuid4()}/items")
    assert response.status_code == 401


async def test_list_requirements_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/v1/tenders/{uuid.uuid4()}/requirements")
    assert response.status_code == 401


async def test_list_items_returns_stored_items(client: httpx.AsyncClient) -> None:
    tender_id = await _create_tender()
    await store_tender_items(
        tender_id,
        "pncp",
        [
            RawTenderItem(
                item_number=1,
                description="Item de teste",
                material_or_service="Material",
                quantity=None,
                unit_of_measure="Unidade",
                unit_estimated_value=None,
                total_estimated_value=None,
            )
        ],
    )
    access_token = await _signup(client)

    response = await client.get(
        f"/v1/tenders/{tender_id}/items",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["item_number"] == 1
    assert items[0]["description"] == "Item de teste"


async def test_list_items_returns_empty_for_tender_without_items(
    client: httpx.AsyncClient,
) -> None:
    tender_id = await _create_tender()
    access_token = await _signup(client)

    response = await client.get(
        f"/v1/tenders/{tender_id}/items",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json() == []
