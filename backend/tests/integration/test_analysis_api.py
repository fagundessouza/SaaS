"""API do dossie (Fase 8): CRUD de Certificate/Attestation em /v1/company-profile e
GET/POST /v1/opportunities/{id}/analysis (ver api/v1/companies.py, api/v1/opportunities.py)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date, timedelta

import httpx
import pytest

from ai_platform.documents.models import (
    Document,
    DocumentVersion,
    ExtractionMethod,
    ExtractionQuality,
    LayoutQuality,
    TableQuality,
)
from api.main import app
from core.db.session import system_session, tenant_session
from core.tenancy.context import tenant_scope
from domains.procurement.opportunities.models import Opportunity
from domains.procurement.tenders.models import Requirement, RequirementCategory, Tender
from tests.conftest import unique_email, unique_text


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _signup(client: httpx.AsyncClient, prefix: str) -> tuple[str, uuid.UUID]:
    signup = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": f"Empresa {prefix}",
            "email": unique_email(prefix),
            "password": "senha-forte-123",
        },
    )
    assert signup.status_code == 201, signup.text
    body = signup.json()
    return str(body["access_token"]), uuid.UUID(body["tenant_id"])


async def _create_opportunity_with_requirement(tenant_id: uuid.UUID, marker: str) -> uuid.UUID:
    async with system_session() as session:
        tender = Tender(
            source="pncp",
            external_id=f"analysis-api-{marker}",
            orgao_cnpj="00394460000141",
            orgao_nome="Orgao Teste",
            unidade_nome=None,
            uf="RN",
            municipio="Cidade Teste",
            modalidade="Pregao Eletronico",
            objeto="Objeto teste",
            valor_estimado=None,
            data_publicacao=None,
            data_abertura_proposta=None,
            data_encerramento_proposta=None,
            situacao=None,
            latest_version_number=1,
        )
        session.add(tender)
        await session.flush()
        tender_id = tender.id

        document = Document(content_hash=f"analysis-api-doc-{marker}", latest_version_number=1)
        session.add(document)
        await session.flush()

        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            processing_version="v1",
            extraction_method=ExtractionMethod.NATIVE,
            extraction_quality=ExtractionQuality.HIGH,
            ocr_required=False,
            layout_quality=LayoutQuality.HIGH,
            table_quality=TableQuality.NOT_APPLICABLE,
            low_extraction_confidence=False,
            page_count=1,
            extracted_text="texto irrelevante",
            page_texts=["texto irrelevante"],
        )
        session.add(version)
        await session.flush()

        session.add(
            Requirement(
                tender_id=tender_id,
                category=RequirementCategory.FISCAL,
                description="certidao negativa de debitos federais",
                confidence=1.0,
                document_version_id=version.id,
                chunk_index=0,
                section="secao fiscal",
                page_start=1,
                page_end=1,
            )
        )

    with tenant_scope(tenant_id):
        async with tenant_session() as session:
            opportunity = Opportunity(tenant_id=tenant_id, tender_id=tender_id)
            session.add(opportunity)
            await session.flush()
            return opportunity.id


async def test_certificates_require_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/company-profile/certificates")
    assert response.status_code == 401


async def test_create_list_and_delete_certificate(client: httpx.AsyncClient) -> None:
    token, _ = await _signup(client, "cert-api")
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/v1/company-profile/certificates",
        headers=headers,
        json={
            "category": "fiscal",
            "name": "CND Federal",
            "expires_at": (date.today() + timedelta(days=30)).isoformat(),
        },
    )
    assert create.status_code == 201, create.text
    certificate_id = create.json()["id"]

    listing = await client.get("/v1/company-profile/certificates", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert listing.json()[0]["name"] == "CND Federal"

    delete = await client.delete(
        f"/v1/company-profile/certificates/{certificate_id}", headers=headers
    )
    assert delete.status_code == 204

    listing_after = await client.get("/v1/company-profile/certificates", headers=headers)
    assert listing_after.json() == []


async def test_create_list_and_delete_attestation(client: httpx.AsyncClient) -> None:
    token, _ = await _signup(client, "att-api")
    headers = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/v1/company-profile/attestations",
        headers=headers,
        json={
            "issuing_org": "Prefeitura Exemplo",
            "object_description": "Desenvolvimento de sistema de software sob medida",
        },
    )
    assert create.status_code == 201, create.text
    attestation_id = create.json()["id"]

    listing = await client.get("/v1/company-profile/attestations", headers=headers)
    assert len(listing.json()) == 1

    delete = await client.delete(
        f"/v1/company-profile/attestations/{attestation_id}", headers=headers
    )
    assert delete.status_code == 204
    assert (await client.get("/v1/company-profile/attestations", headers=headers)).json() == []


async def test_analysis_returns_404_before_generation(client: httpx.AsyncClient) -> None:
    token, tenant_id = await _signup(client, "analysis-404")
    headers = {"Authorization": f"Bearer {token}"}
    opportunity_id = await _create_opportunity_with_requirement(
        tenant_id, unique_text("api-404")[:20].replace(" ", "-")
    )

    response = await client.get(f"/v1/opportunities/{opportunity_id}/analysis", headers=headers)
    assert response.status_code == 404


async def test_generate_and_fetch_analysis_via_api(client: httpx.AsyncClient) -> None:
    token, tenant_id = await _signup(client, "analysis-gen")
    headers = {"Authorization": f"Bearer {token}"}
    marker = unique_text("api-gen")[:20].replace(" ", "-")
    opportunity_id = await _create_opportunity_with_requirement(tenant_id, marker)

    generate = await client.post(
        f"/v1/opportunities/{opportunity_id}/analysis", headers=headers
    )
    assert generate.status_code == 201, generate.text
    body = generate.json()
    assert body["opportunity_id"] == str(opportunity_id)
    assert len(body["findings"]) == 1
    assert body["findings"][0]["status"] == "missing"  # nenhuma certidao cadastrada ainda
    assert body["findings"][0]["evidence"][0]["kind"] == "requirement_text"

    fetch = await client.get(f"/v1/opportunities/{opportunity_id}/analysis", headers=headers)
    assert fetch.status_code == 200
    assert fetch.json()["id"] == body["id"]
