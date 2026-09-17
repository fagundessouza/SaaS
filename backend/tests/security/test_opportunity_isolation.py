"""Isolamento de tenant para as tabelas da Fase 7 (opportunities, opportunity_matches).

`opportunity_matches` tem RLS propria apesar de ser DERIVADA de Opportunity no DOMAIN_MODEL —
defesa em profundidade (ver docstring do modelo e DECISOES da Fase 7). Estes testes provam as
duas barreiras: a query do dominio (que nem filtra tenant_id manualmente, confia no RLS) e o
caminho fim a fim pela API com token de outro tenant.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date

import httpx
import pytest
from sqlalchemy import select

from api.main import app
from core.auth.service import create_tenant_with_owner
from core.db.session import tenant_session
from core.tenancy.context import tenant_scope
from domains.procurement.opportunities.matching import MatchEvaluation
from domains.procurement.opportunities.models import Opportunity, OpportunityMatch
from domains.procurement.opportunities.service import create_opportunity_from_match
from domains.procurement.tenders.service import ingest_raw_tender
from ingestion.connectors.base import RawTender
from tests.conftest import unique_email

_EVALUATION = MatchEvaluation(
    matched=True,
    compatibility={"region": {"matched": True, "tender_uf": "RN", "profile_regions": ["RN"]}},
    confidence={"region": 1.0},
)


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_tender() -> uuid.UUID:
    external_id = f"opp-isola-{uuid.uuid4()}"
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


async def test_opportunity_of_one_tenant_is_invisible_to_another() -> None:
    owner_a = await create_tenant_with_owner(
        company_name="Radar A", email=unique_email("radar-isola-a"), password="senha-forte-123"
    )
    owner_b = await create_tenant_with_owner(
        company_name="Radar B", email=unique_email("radar-isola-b"), password="senha-forte-123"
    )
    tender_id = await _create_tender()

    with tenant_scope(owner_a.tenant_id):
        opportunity_id = await create_opportunity_from_match(
            tenant_id=owner_a.tenant_id, tender_id=tender_id, evaluation=_EVALUATION
        )
    assert opportunity_id is not None

    # A query do tenant B nao filtra tenant_id de proposito: quem tem de barrar e o RLS.
    with tenant_scope(owner_b.tenant_id):
        async with tenant_session() as session:
            opportunities = (await session.execute(select(Opportunity))).scalars().all()
            matches = (await session.execute(select(OpportunityMatch))).scalars().all()

    assert all(row.tenant_id == owner_b.tenant_id for row in opportunities)
    assert opportunity_id not in [row.id for row in opportunities]
    assert all(row.tenant_id == owner_b.tenant_id for row in matches)
    assert opportunity_id not in [row.opportunity_id for row in matches]


async def test_the_same_tender_generates_one_opportunity_per_tenant() -> None:
    """O mesmo edital (GLOBAL) gera N Opportunity independentes, uma por tenant — cada uma com
    seu proprio ciclo de vida. A constraint de unicidade e por (tenant_id, tender_id), nunca por
    tender_id sozinho (ver DOMAIN_MODEL: nao confundir Tender com Opportunity)."""
    owner_a = await create_tenant_with_owner(
        company_name="Radar C", email=unique_email("radar-isola-c"), password="senha-forte-123"
    )
    owner_b = await create_tenant_with_owner(
        company_name="Radar D", email=unique_email("radar-isola-d"), password="senha-forte-123"
    )
    tender_id = await _create_tender()

    with tenant_scope(owner_a.tenant_id):
        opportunity_a = await create_opportunity_from_match(
            tenant_id=owner_a.tenant_id, tender_id=tender_id, evaluation=_EVALUATION
        )
    with tenant_scope(owner_b.tenant_id):
        opportunity_b = await create_opportunity_from_match(
            tenant_id=owner_b.tenant_id, tender_id=tender_id, evaluation=_EVALUATION
        )

    assert opportunity_a is not None
    assert opportunity_b is not None
    assert opportunity_a != opportunity_b


async def test_api_token_of_another_tenant_cannot_change_status(
    client: httpx.AsyncClient,
) -> None:
    """Fim a fim: mesmo sabendo o id da Opportunity de outro tenant, o token nao a alcanca — a
    resposta e 404 (nao 403), porque para este tenant o recurso simplesmente nao existe."""
    signup_a = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "API Radar A",
            "email": unique_email("api-radar-a"),
            "password": "senha-forte-123",
        },
    )
    signup_b = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "API Radar B",
            "email": unique_email("api-radar-b"),
            "password": "senha-forte-123",
        },
    )
    tenant_a = uuid.UUID(signup_a.json()["tenant_id"])
    token_b = signup_b.json()["access_token"]

    tender_id = await _create_tender()
    with tenant_scope(tenant_a):
        opportunity_id = await create_opportunity_from_match(
            tenant_id=tenant_a, tender_id=tender_id, evaluation=_EVALUATION
        )

    response = await client.patch(
        f"/v1/opportunities/{opportunity_id}/status",
        json={"status": "under_review"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404

    listing = await client.get("/v1/opportunities", headers={"Authorization": f"Bearer {token_b}"})
    assert listing.json() == []
