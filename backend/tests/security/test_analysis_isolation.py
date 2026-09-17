"""Isolamento de tenant para as tabelas da Fase 8 (certificates, attestations, analyses,
findings, evidences) — mesmo padrao de tests/security/test_opportunity_isolation.py (Fase 7):
prova a barreira em duas camadas, a query de dominio (que nao filtra tenant_id manualmente,
confia no RLS) e o caminho fim a fim pela API com token de outro tenant.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select

from ai_platform.documents.models import (
    Document,
    DocumentVersion,
    ExtractionMethod,
    ExtractionQuality,
    LayoutQuality,
    TableQuality,
)
from api.main import app
from core.auth.service import create_tenant_with_owner
from core.db.session import system_session, tenant_session
from core.tenancy.context import tenant_scope
from domains.procurement.analysis.models import Analysis, Evidence, Finding
from domains.procurement.analysis.service import generate_analysis
from domains.procurement.companies.models import Attestation, Certificate, CompanyProfile
from domains.procurement.opportunities.models import Opportunity
from domains.procurement.tenders.models import Requirement, RequirementCategory, Tender
from tests.conftest import unique_email


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_tenant_with_full_setup(prefix: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Cria Tenant + owner + CompanyProfile + Tender com 1 Requirement + Opportunity + Analysis
    ja gerada, com uma Certificate e uma Attestation cadastradas. Retorna (tenant_id,
    opportunity_id)."""
    owner = await create_tenant_with_owner(
        company_name=f"Empresa {prefix}", email=unique_email(prefix), password="senha-forte-123"
    )

    async with system_session() as session:
        tender = Tender(
            source="pncp",
            external_id=f"analysis-isola-{prefix}-{uuid.uuid4()}",
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

        document = Document(
            content_hash=uuid.uuid4().hex, latest_version_number=1
        )
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

    with tenant_scope(owner.tenant_id):
        async with tenant_session() as session:
            profile = CompanyProfile(tenant_id=owner.tenant_id, legal_name=f"Empresa {prefix}")
            session.add(profile)
            await session.flush()

            session.add(
                Certificate(
                    tenant_id=owner.tenant_id,
                    company_profile_id=profile.id,
                    category=RequirementCategory.FISCAL,
                    name="CND Federal",
                    expires_at=date.today() + timedelta(days=30),
                )
            )
            session.add(
                Attestation(
                    tenant_id=owner.tenant_id,
                    company_profile_id=profile.id,
                    issuing_org="Orgao Exemplo",
                    object_description="Experiencia anterior relevante",
                )
            )

            opportunity = Opportunity(tenant_id=owner.tenant_id, tender_id=tender_id)
            session.add(opportunity)
            await session.flush()
            opportunity_id = opportunity.id

        await generate_analysis(opportunity_id)

    return owner.tenant_id, opportunity_id


async def test_certificates_and_attestations_of_one_tenant_are_invisible_to_another() -> None:
    tenant_a, _ = await _create_tenant_with_full_setup("cert-isola-a")
    tenant_b, _ = await _create_tenant_with_full_setup("cert-isola-b")

    # Query do tenant B nao filtra tenant_id de proposito: quem tem de barrar e o RLS.
    with tenant_scope(tenant_b):
        async with tenant_session() as session:
            certificates = (await session.execute(select(Certificate))).scalars().all()
            attestations = (await session.execute(select(Attestation))).scalars().all()

    assert all(row.tenant_id == tenant_b for row in certificates)
    assert all(row.tenant_id == tenant_b for row in attestations)
    assert tenant_a not in {row.tenant_id for row in certificates}
    assert tenant_a not in {row.tenant_id for row in attestations}


async def test_analyses_findings_and_evidences_of_one_tenant_are_invisible_to_another() -> None:
    tenant_a, opportunity_a = await _create_tenant_with_full_setup("dossie-isola-a")
    tenant_b, _ = await _create_tenant_with_full_setup("dossie-isola-b")

    with tenant_scope(tenant_b):
        async with tenant_session() as session:
            analyses = (await session.execute(select(Analysis))).scalars().all()
            findings = (await session.execute(select(Finding))).scalars().all()
            evidences = (await session.execute(select(Evidence))).scalars().all()

    assert all(row.tenant_id == tenant_b for row in analyses)
    assert all(row.tenant_id == tenant_b for row in findings)
    assert all(row.tenant_id == tenant_b for row in evidences)
    assert opportunity_a not in {row.opportunity_id for row in analyses}


async def test_api_token_of_another_tenant_cannot_fetch_analysis(
    client: httpx.AsyncClient,
) -> None:
    """Fim a fim: mesmo sabendo o id da Opportunity/Analysis de outro tenant, o token nao a
    alcanca — 404, nao 403 (para este tenant o recurso simplesmente nao existe), mesmo padrao ja
    provado para Opportunity na Fase 7."""
    _, opportunity_a = await _create_tenant_with_full_setup("dossie-api-a")

    signup_b = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "Empresa B API",
            "email": unique_email("dossie-api-b"),
            "password": "senha-forte-123",
        },
    )
    token_b = signup_b.json()["access_token"]

    response = await client.get(
        f"/v1/opportunities/{opportunity_a}/analysis",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response.status_code == 404
