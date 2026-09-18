"""domains/assistant/service.py contra Postgres real (sem mock de banco) — LLMProvider injetado
como fake deterministico, ja que nenhuma credencial de LLM real existe neste ambiente (ver
docs/phase-reports/FASE_9_REPORT.md, RISCOS). O que importa testar geninamente aqui e o
CONTEXTO montado por query deterministica e as citacoes estruturadas, nao o texto gerado pelo
modelo em si — mesmo raciocinio ja aplicado pela fronteira regra-vs-IA do ADR-0007.
"""

from __future__ import annotations

import uuid

import pytest

from ai_platform.documents.models import (
    Document,
    DocumentVersion,
    ExtractionMethod,
    ExtractionQuality,
    LayoutQuality,
    TableQuality,
)
from ai_platform.llm.provider import LLMMessage
from core.auth.service import create_tenant_with_owner
from core.db.session import system_session, tenant_session
from core.tenancy.context import tenant_scope
from domains.assistant.models import AssistantAction, AssistantMessageRole
from domains.assistant.service import RequirementNotFoundError, run_action
from domains.procurement.companies.models import CompanyProfile
from domains.procurement.opportunities.models import Opportunity
from domains.procurement.tenders.models import Requirement, RequirementCategory, Tender, TenderItem
from tests.conftest import unique_email


class _FakeLLM:
    model_name = "fake-model"

    def __init__(self) -> None:
        self.received_contexts: list[str] = []

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> str:
        user_message = next(m for m in messages if m.role.value == "user")
        self.received_contexts.append(user_message.content)
        return f"resposta sintética para: {user_message.content[:40]}"


async def _setup_tender_with_requirement(marker: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with system_session() as session:
        tender = Tender(
            source="pncp",
            external_id=f"assistant-test-{marker}",
            orgao_cnpj="00394460000141",
            orgao_nome="Orgao Teste",
            unidade_nome=None,
            uf="RN",
            municipio="Cidade Teste",
            modalidade="Pregão Eletrônico",
            objeto="Aquisição de material de escritório",
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

        session.add(
            TenderItem(
                tender_id=tender_id,
                item_number=1,
                description="Papel A4",
                material_or_service="Material",
                quantity=100,
                unit_of_measure="resma",
                unit_estimated_value=None,
                total_estimated_value=None,
            )
        )

        document = Document(content_hash=f"assistant-doc-{marker}", latest_version_number=1)
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
            category=RequirementCategory.JURIDICA,
            description="a) contrato social registrado na junta comercial.",
            confidence=1.0,
            document_version_id=version.id,
            chunk_index=0,
            section="8. DA HABILITAÇÃO",
            page_start=1,
            page_end=1,
        )
        session.add(requirement)
        await session.flush()
        requirement_id = requirement.id

    return tender_id, requirement_id, version.id


async def _setup_tenant_with_opportunity(
    prefix: str, tender_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    owner = await create_tenant_with_owner(
        company_name=f"Empresa {prefix}", email=unique_email(prefix), password="senha-forte-123"
    )
    with tenant_scope(owner.tenant_id):
        async with tenant_session() as session:
            session.add(CompanyProfile(tenant_id=owner.tenant_id, legal_name=f"Empresa {prefix}"))
            opportunity = Opportunity(tenant_id=owner.tenant_id, tender_id=tender_id)
            session.add(opportunity)
            await session.flush()
            opportunity_id = opportunity.id
    return owner.tenant_id, owner.user_id, opportunity_id


async def test_missing_requirements_generates_analysis_on_demand_and_cites_evidence() -> None:
    marker = uuid.uuid4().hex[:8]
    tender_id, requirement_id, _ = await _setup_tender_with_requirement(marker)
    tenant_id, user_id, opportunity_id = await _setup_tenant_with_opportunity(
        f"assist-missing-{marker[:8]}", tender_id
    )
    fake_llm = _FakeLLM()

    with tenant_scope(tenant_id):
        message = await run_action(
            tenant_id=tenant_id,
            user_id=user_id,
            opportunity_id=opportunity_id,
            action=AssistantAction.MISSING_REQUIREMENTS,
            provider=fake_llm,
        )

    assert message.role == AssistantMessageRole.ASSISTANT
    assert message.action == AssistantAction.MISSING_REQUIREMENTS
    assert len(message.evidence_refs) == 1
    ref = message.evidence_refs[0]
    assert ref["status"] == "missing"  # nenhuma Certificate cadastrada
    assert ref["evidence"][0]["section"] == "8. DA HABILITAÇÃO"
    assert "juridica" in fake_llm.received_contexts[0].lower()
    assert "faltando" in fake_llm.received_contexts[0].lower()


async def test_understand_tender_cites_tender_and_item_count() -> None:
    marker = uuid.uuid4().hex[:8]
    tender_id, _, _ = await _setup_tender_with_requirement(marker)
    tenant_id, user_id, opportunity_id = await _setup_tenant_with_opportunity(
        f"assist-understand-{marker[:8]}", tender_id
    )
    fake_llm = _FakeLLM()

    with tenant_scope(tenant_id):
        message = await run_action(
            tenant_id=tenant_id,
            user_id=user_id,
            opportunity_id=opportunity_id,
            action=AssistantAction.UNDERSTAND_TENDER,
            provider=fake_llm,
        )

    assert message.evidence_refs == [{"tender_id": str(tender_id), "item_count": 1}]
    assert "material de escritório" in fake_llm.received_contexts[0].lower()


async def test_explain_requirement_cites_section_and_page() -> None:
    marker = uuid.uuid4().hex[:8]
    tender_id, requirement_id, _ = await _setup_tender_with_requirement(marker)
    tenant_id, user_id, opportunity_id = await _setup_tenant_with_opportunity(
        f"assist-explain-{marker[:8]}", tender_id
    )
    fake_llm = _FakeLLM()

    with tenant_scope(tenant_id):
        message = await run_action(
            tenant_id=tenant_id,
            user_id=user_id,
            opportunity_id=opportunity_id,
            action=AssistantAction.EXPLAIN_REQUIREMENT,
            requirement_id=requirement_id,
            provider=fake_llm,
        )

    assert message.evidence_refs[0]["requirement_id"] == str(requirement_id)
    assert message.evidence_refs[0]["section"] == "8. DA HABILITAÇÃO"


async def test_explain_requirement_raises_for_unknown_requirement() -> None:
    marker = uuid.uuid4().hex[:8]
    tender_id, _, _ = await _setup_tender_with_requirement(marker)
    tenant_id, user_id, opportunity_id = await _setup_tenant_with_opportunity(
        f"assist-404-{marker[:8]}", tender_id
    )

    with tenant_scope(tenant_id), pytest.raises(RequirementNotFoundError):
        await run_action(
            tenant_id=tenant_id,
            user_id=user_id,
            opportunity_id=opportunity_id,
            action=AssistantAction.EXPLAIN_REQUIREMENT,
            requirement_id=uuid.uuid4(),
            provider=_FakeLLM(),
        )


async def test_repeated_actions_reuse_the_same_session() -> None:
    marker = uuid.uuid4().hex[:8]
    tender_id, _, _ = await _setup_tender_with_requirement(marker)
    tenant_id, user_id, opportunity_id = await _setup_tenant_with_opportunity(
        f"assist-reuse-{marker[:8]}", tender_id
    )
    fake_llm = _FakeLLM()

    with tenant_scope(tenant_id):
        first = await run_action(
            tenant_id=tenant_id, user_id=user_id, opportunity_id=opportunity_id,
            action=AssistantAction.UNDERSTAND_TENDER, provider=fake_llm,
        )
        second = await run_action(
            tenant_id=tenant_id, user_id=user_id, opportunity_id=opportunity_id,
            action=AssistantAction.MISSING_REQUIREMENTS, provider=fake_llm,
        )

    assert first.session_id == second.session_id
