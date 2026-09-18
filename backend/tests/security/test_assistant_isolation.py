"""Isolamento de tenant para as tabelas da Fase 9 (assistant_sessions, assistant_messages) —
mesmo padrao de tests/security/test_notification_isolation.py (Fase 10)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from ai_platform.llm.provider import LLMMessage
from core.auth.service import create_tenant_with_owner
from core.db.session import system_session, tenant_session
from core.tenancy.context import tenant_scope
from domains.assistant.models import AssistantAction, AssistantMessage, AssistantSession
from domains.assistant.service import run_action
from domains.procurement.companies.models import CompanyProfile
from domains.procurement.opportunities.models import Opportunity
from domains.procurement.tenders.models import Tender
from tests.conftest import unique_email


class _FakeLLM:
    model_name = "fake-model"

    async def complete(self, messages: list[LLMMessage], *, max_tokens: int) -> str:
        return "resposta fake"


async def _create_tenant_with_assistant_history(prefix: str) -> uuid.UUID:
    owner = await create_tenant_with_owner(
        company_name=f"Empresa {prefix}", email=unique_email(prefix), password="senha-forte-123"
    )

    async with system_session() as session:
        tender = Tender(
            source="pncp",
            external_id=f"assistant-isola-{uuid.uuid4()}",
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

    with tenant_scope(owner.tenant_id):
        async with tenant_session() as session:
            session.add(CompanyProfile(tenant_id=owner.tenant_id, legal_name=f"Empresa {prefix}"))
            opportunity = Opportunity(tenant_id=owner.tenant_id, tender_id=tender_id)
            session.add(opportunity)
            await session.flush()
            opportunity_id = opportunity.id

        await run_action(
            tenant_id=owner.tenant_id,
            user_id=owner.user_id,
            opportunity_id=opportunity_id,
            action=AssistantAction.UNDERSTAND_TENDER,
            provider=_FakeLLM(),
        )

    return owner.tenant_id


async def test_assistant_tables_of_one_tenant_are_invisible_to_another() -> None:
    tenant_a = await _create_tenant_with_assistant_history("assistant-isola-a")
    tenant_b = await _create_tenant_with_assistant_history("assistant-isola-b")

    # Query do tenant B nao filtra tenant_id de proposito: quem tem de barrar e o RLS.
    with tenant_scope(tenant_b):
        async with tenant_session() as session:
            sessions = (await session.execute(select(AssistantSession))).scalars().all()
            messages = (await session.execute(select(AssistantMessage))).scalars().all()

    assert all(row.tenant_id == tenant_b for row in sessions)
    assert all(row.tenant_id == tenant_b for row in messages)
    assert tenant_a not in {row.tenant_id for row in sessions}
