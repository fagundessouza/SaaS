"""API do Assistente (ver api/v1/assistant.py). O caminho feliz e testado com o provider real
(`openai_compatible`) configurado via settings + respx mockando o endpoint HTTP — prova que a
rota liga corretamente `run_action` -> `get_llm_provider()` -> o provider de verdade, sem
depender de credencial real (nenhuma existe neste ambiente, ver
docs/phase-reports/FASE_9_REPORT.md)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
import respx

from ai_platform.documents.models import (
    Document,
    DocumentVersion,
    ExtractionMethod,
    ExtractionQuality,
    LayoutQuality,
    TableQuality,
)
from ai_platform.llm.provider import get_llm_provider
from api.main import app
from core.config import get_settings
from core.db.session import system_session, tenant_session
from core.tenancy.context import tenant_scope
from domains.procurement.opportunities.models import Opportunity
from domains.procurement.tenders.models import Requirement, RequirementCategory, Tender
from tests.conftest import unique_email


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


async def _create_tender_with_requirement() -> tuple[uuid.UUID, uuid.UUID]:
    async with system_session() as session:
        tender = Tender(
            source="pncp",
            external_id=f"assistant-api-{uuid.uuid4()}",
            orgao_cnpj="00394460000141",
            orgao_nome="Orgao Teste",
            unidade_nome=None,
            uf="RN",
            municipio="Cidade Teste",
            modalidade="Pregão Eletrônico",
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

        document = Document(content_hash=f"assistant-api-{uuid.uuid4()}", latest_version_number=1)
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
            extracted_text="x",
            page_texts=["x"],
        )
        session.add(version)
        await session.flush()

        requirement = Requirement(
            tender_id=tender_id,
            category=RequirementCategory.TECNICA,
            description="atestado de capacidade tecnica",
            confidence=1.0,
            document_version_id=version.id,
            chunk_index=0,
            section="9. QUALIFICAÇÃO TÉCNICA",
            page_start=1,
            page_end=1,
        )
        session.add(requirement)
        await session.flush()
        return tender_id, requirement.id


async def _create_opportunity(tenant_id: uuid.UUID, tender_id: uuid.UUID) -> uuid.UUID:
    with tenant_scope(tenant_id):
        async with tenant_session() as session:
            opportunity = Opportunity(tenant_id=tenant_id, tender_id=tender_id)
            session.add(opportunity)
            await session.flush()
            return opportunity.id


async def test_assistant_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/assistant/actions",
        json={"opportunity_id": str(uuid.uuid4()), "action": "understand_tender"},
    )
    assert response.status_code == 401


async def test_assistant_returns_404_for_unknown_opportunity(client: httpx.AsyncClient) -> None:
    token, _ = await _signup(client, "assistant-404")

    response = await client.post(
        "/v1/assistant/actions",
        headers={"Authorization": f"Bearer {token}"},
        json={"opportunity_id": str(uuid.uuid4()), "action": "understand_tender"},
    )
    assert response.status_code == 404


async def test_assistant_returns_503_when_llm_not_configured(client: httpx.AsyncClient) -> None:
    """Estado padrao deste ambiente (nenhuma credencial de LLM configurada, ver .env.example) —
    o endpoint falha de forma explicita, nunca finge uma resposta (ver
    LLMProviderNotConfiguredError). Garantido chamando `get_settings()`/`get_llm_provider()`
    com o `.env` real deste ambiente, sem nenhum override de configuracao."""
    get_settings.cache_clear()
    get_llm_provider.cache_clear()

    token, tenant_id = await _signup(client, "assistant-503")
    tender_id, _ = await _create_tender_with_requirement()
    opportunity_id = await _create_opportunity(tenant_id, tender_id)

    response = await client.post(
        "/v1/assistant/actions",
        headers={"Authorization": f"Bearer {token}"},
        json={"opportunity_id": str(opportunity_id), "action": "understand_tender"},
    )
    assert response.status_code == 503


async def test_assistant_happy_path_via_real_provider_with_mocked_http(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODEL_NAME", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "http://fake-llm.local/v1")
    get_settings.cache_clear()
    get_llm_provider.cache_clear()

    token, tenant_id = await _signup(client, "assistant-happy")
    tender_id, requirement_id = await _create_tender_with_requirement()
    opportunity_id = await _create_opportunity(tenant_id, tender_id)

    with respx.mock:
        respx.post("http://fake-llm.local/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Este requisito exige atestado."}}]},
            )
        )

        response = await client.post(
            "/v1/assistant/actions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "opportunity_id": str(opportunity_id),
                "action": "explain_requirement",
                "requirement_id": str(requirement_id),
            },
        )

    get_settings.cache_clear()
    get_llm_provider.cache_clear()

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["content"] == "Este requisito exige atestado."
    assert body["evidence_refs"][0]["requirement_id"] == str(requirement_id)
