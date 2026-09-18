"""GET/PATCH /v1/opportunities — radar do tenant e transicoes do ciclo de vida
(ver api/v1/opportunities.py e domains/procurement/opportunities/service.py)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import httpx
import pytest

from api.main import app
from core.tenancy.context import tenant_scope
from domains.procurement.opportunities.matching import MatchEvaluation
from domains.procurement.opportunities.service import create_opportunity_from_match
from domains.procurement.tenders.service import ingest_raw_tender
from ingestion.connectors.base import RawTender
from tests.conftest import unique_email

_EVALUATION = MatchEvaluation(
    matched=True,
    compatibility={
        "region": {"matched": True, "tender_uf": "RN", "profile_regions": ["RN"]},
        "keyword": {"matched": True, "matched_terms": ["material de escritorio"]},
    },
    confidence={"region": 1.0, "keyword": 1.0},
)


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_tender() -> uuid.UUID:
    external_id = f"opp-api-{uuid.uuid4()}"
    raw = RawTender(
        source="pncp",
        external_id=external_id,
        orgao_cnpj="00394460000141",
        orgao_nome="Prefeitura Exemplo",
        unidade_nome=None,
        uf="RN",
        municipio="Cidade Exemplo",
        modalidade="Pregao Eletronico",
        objeto="Aquisicao de material de escritorio",
        valor_estimado=None,
        data_publicacao=date(2026, 9, 17),
        data_abertura_proposta=None,
        data_encerramento_proposta=None,
        situacao=None,
        ano_compra=2026,
        sequencial_compra=1,
        raw_payload={"numeroControlePNCP": external_id},
        documents=[],
    )
    result = await ingest_raw_tender(raw)
    return result.tender_id


async def _signup_with_opportunity(client: httpx.AsyncClient) -> tuple[str, uuid.UUID, uuid.UUID]:
    signup = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "Empresa Radar API",
            "email": unique_email("radar-api"),
            "password": "senha-forte-123",
        },
    )
    body = signup.json()
    token = str(body["access_token"])
    tenant_id = uuid.UUID(body["tenant_id"])

    tender_id = await _create_tender()
    with tenant_scope(tenant_id):
        opportunity_id = await create_opportunity_from_match(
            tenant_id=tenant_id, tender_id=tender_id, evaluation=_EVALUATION
        )
    assert opportunity_id is not None
    return token, tenant_id, opportunity_id


async def test_list_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/opportunities")
    assert response.status_code == 401


async def test_list_returns_opportunity_with_decomposed_match(client: httpx.AsyncClient) -> None:
    token, _, opportunity_id = await _signup_with_opportunity(client)

    response = await client.get("/v1/opportunities", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == str(opportunity_id)
    assert row["status"] == "discovered"
    # O contrato da API expoe os fatores, nunca um score unico agregado.
    assert row["compatibility"]["region"]["matched"] is True
    assert row["confidence"] == {"region": 1.0, "keyword": 1.0}
    assert "score" not in row


async def test_get_single_opportunity_returns_decomposed_match(
    client: httpx.AsyncClient,
) -> None:
    token, _, opportunity_id = await _signup_with_opportunity(client)

    response = await client.get(
        f"/v1/opportunities/{opportunity_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(opportunity_id)
    assert body["compatibility"]["region"]["matched"] is True


async def test_get_single_opportunity_returns_404_for_unknown_id(
    client: httpx.AsyncClient,
) -> None:
    token, _, _ = await _signup_with_opportunity(client)

    response = await client.get(
        f"/v1/opportunities/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


async def test_valid_status_transition_is_applied(client: httpx.AsyncClient) -> None:
    token, _, opportunity_id = await _signup_with_opportunity(client)

    response = await client.patch(
        f"/v1/opportunities/{opportunity_id}/status",
        json={"status": "under_review"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "under_review"


async def test_invalid_status_transition_is_rejected_with_conflict(
    client: httpx.AsyncClient,
) -> None:
    """DISCOVERED -> SUBMITTED pula o workflow inteiro: e conflito de estado (409), nao erro de
    payload (422)."""
    token, _, opportunity_id = await _signup_with_opportunity(client)

    response = await client.patch(
        f"/v1/opportunities/{opportunity_id}/status",
        json={"status": "submitted"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
    assert "discovered" in response.json()["detail"]


async def test_terminal_status_accepts_no_further_transition(client: httpx.AsyncClient) -> None:
    token, _, opportunity_id = await _signup_with_opportunity(client)
    headers = {"Authorization": f"Bearer {token}"}

    withdrawn = await client.patch(
        f"/v1/opportunities/{opportunity_id}/status",
        json={"status": "withdrawn"},
        headers=headers,
    )
    assert withdrawn.status_code == 200

    reopened = await client.patch(
        f"/v1/opportunities/{opportunity_id}/status",
        json={"status": "under_review"},
        headers=headers,
    )
    assert reopened.status_code == 409


async def test_only_active_filter_excludes_closed_opportunities(
    client: httpx.AsyncClient,
) -> None:
    token, _, opportunity_id = await _signup_with_opportunity(client)
    headers = {"Authorization": f"Bearer {token}"}

    await client.patch(
        f"/v1/opportunities/{opportunity_id}/status",
        json={"status": "withdrawn"},
        headers=headers,
    )

    active = await client.get("/v1/opportunities", params={"only_active": True}, headers=headers)
    assert active.json() == []

    everything = await client.get("/v1/opportunities", headers=headers)
    assert len(everything.json()) == 1


async def test_assignee_can_be_set_and_cleared(client: httpx.AsyncClient) -> None:
    token, tenant_id, opportunity_id = await _signup_with_opportunity(client)
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/v1/users/me", headers=headers)
    user_id = me.json()["id"]

    assigned = await client.patch(
        f"/v1/opportunities/{opportunity_id}/assignee",
        json={"user_id": user_id},
        headers=headers,
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_to_user_id"] == user_id

    cleared = await client.patch(
        f"/v1/opportunities/{opportunity_id}/assignee",
        json={"user_id": None},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["assigned_to_user_id"] is None


async def test_unknown_opportunity_returns_404(client: httpx.AsyncClient) -> None:
    token, _, _ = await _signup_with_opportunity(client)

    response = await client.patch(
        f"/v1/opportunities/{uuid.uuid4()}/status",
        json={"status": "under_review"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_commercial_profile_endpoint_feeds_the_matching_engine(
    client: httpx.AsyncClient,
) -> None:
    """O endpoint de perfil comercial e a unica porta de entrada de products/services — sem ele,
    o radar de qualquer tenant novo fica vazio por construcao."""
    signup = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "Empresa Comercial",
            "email": unique_email("comercial"),
            "password": "senha-forte-123",
        },
    )
    token = signup.json()["access_token"]

    response = await client.put(
        "/v1/company-profile/commercial",
        json={
            "regions": ["rn", " pb "],
            "products": ["material de escritorio", "  "],
            "services": ["entrega expressa"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["regions"] == ["RN", "PB"]  # normalizado para sigla maiuscula
    assert body["products"] == ["material de escritorio"]  # termo vazio descartado
    assert body["services"] == ["entrega expressa"]
