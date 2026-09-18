"""Executa uma AssistantAction: monta contexto por query deterministica (nunca aceita do
cliente, ver UX_AND_ASSISTANT_SPEC.md), chama o LLMProvider so para sintetizar o texto em
linguagem natural, e persiste o par de mensagens (USER com a acao, ASSISTANT com a resposta +
citacoes estruturadas). Vive em `domains/` (nao `ai_platform/`) porque cruza
opportunities/analysis/tenders — conhecimento de dominio que `ai_platform` nao tem.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from ai_platform.llm.provider import LLMMessage, LLMProvider, LLMRole, get_llm_provider
from core.db.session import system_session, tenant_session
from core.observability.logging import get_logger
from core.observability.metrics import assistant_actions_total
from domains.assistant.models import (
    AssistantAction,
    AssistantMessage,
    AssistantMessageRole,
    AssistantSession,
)
from domains.procurement.analysis.models import FindingStatus
from domains.procurement.analysis.service import (
    AnalysisNotFoundError,
    generate_analysis,
    get_analysis_with_findings,
)
from domains.procurement.opportunities.models import Opportunity
from domains.procurement.tenders.models import Requirement, Tender, TenderItem

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "Voce e o assistente de uma plataforma de inteligencia em licitacoes publicas brasileiras. "
    "Responda em portugues do Brasil, de forma direta e objetiva. Use SOMENTE os fatos "
    "fornecidos no contexto abaixo — nunca invente numero de processo, prazo, valor, requisito "
    "ou qualquer outro dado que nao esteja explicitamente no contexto. Se o contexto nao tiver "
    "informacao suficiente para responder algo, diga isso claramente em vez de adivinhar. Nunca "
    "afirme uma conclusao juridica definitiva — descreva o que o texto diz, nao o que ele "
    "significa legalmente."
)


class OpportunityNotFoundError(Exception):
    pass


class RequirementNotFoundError(Exception):
    pass


async def _get_or_create_session(
    *, tenant_id: uuid.UUID, user_id: uuid.UUID, opportunity_id: uuid.UUID
) -> uuid.UUID:
    async with tenant_session() as session:
        existing = await session.execute(
            select(AssistantSession.id).where(
                AssistantSession.user_id == user_id,
                AssistantSession.opportunity_id == opportunity_id,
            )
        )
        session_id = existing.scalar_one_or_none()
        if session_id is not None:
            return session_id

        assistant_session = AssistantSession(
            tenant_id=tenant_id, user_id=user_id, opportunity_id=opportunity_id
        )
        session.add(assistant_session)
        await session.flush()
        return assistant_session.id


async def _persist_turn(
    *,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    action: AssistantAction,
    answer: str,
    evidence_refs: list[dict[str, object]],
) -> AssistantMessage:
    async with tenant_session() as session:
        session.add(
            AssistantMessage(
                tenant_id=tenant_id,
                session_id=session_id,
                role=AssistantMessageRole.USER,
                action=action,
                content=action.value,
                evidence_refs=[],
            )
        )
        assistant_message = AssistantMessage(
            tenant_id=tenant_id,
            session_id=session_id,
            role=AssistantMessageRole.ASSISTANT,
            action=action,
            content=answer,
            evidence_refs=evidence_refs,
        )
        session.add(assistant_message)
        await session.flush()
        return assistant_message


def _finding_status_label(status: FindingStatus) -> str:
    return {
        FindingStatus.MISSING: "faltando",
        FindingStatus.EXPIRED: "vencido",
        FindingStatus.NEEDS_REVIEW: "precisa revisão manual",
        FindingStatus.MET: "atendido",
    }[status]


async def _handle_missing_requirements(
    *, tenant_id: uuid.UUID, opportunity_id: uuid.UUID
) -> tuple[str, list[dict[str, object]]]:
    try:
        _, findings = await get_analysis_with_findings(opportunity_id)
    except AnalysisNotFoundError:
        # Nenhuma Analysis gerada ainda para esta Opportunity — gera sob demanda, para que "o
        # que esta faltando?" funcione mesmo antes do usuario ter clicado em "gerar dossie"
        # explicitamente na tela de Analysis (Fase 8).
        await generate_analysis(opportunity_id)
        _, findings = await get_analysis_with_findings(opportunity_id)

    pending = [(f, ev) for f, ev in findings if f.status != FindingStatus.MET]

    if not pending:
        return (
            "Todos os requisitos de habilitação identificados neste edital estão atendidos "
            "de acordo com os documentos e certidões cadastrados.",
            [],
        )

    lines = []
    evidence_refs: list[dict[str, object]] = []
    for finding, evidence_list in pending:
        lines.append(
            f"- Categoria {finding.category}, status {_finding_status_label(finding.status)}: "
            f"{finding.summary}"
        )
        evidence_refs.append(
            {
                "finding_id": str(finding.id),
                "category": str(finding.category),
                "status": finding.status.value,
                "evidence": [
                    {
                        "kind": ev.kind.value,
                        "description": ev.description,
                        "section": ev.section,
                        "page_start": ev.page_start,
                        "page_end": ev.page_end,
                    }
                    for ev in evidence_list
                ],
            }
        )

    context = "Pendências identificadas no dossiê desta oportunidade:\n" + "\n".join(lines)
    return context, evidence_refs


async def _handle_understand_tender(
    *, opportunity_id: uuid.UUID
) -> tuple[str, list[dict[str, object]]]:
    async with tenant_session() as session:
        opportunity = await session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(str(opportunity_id))
        tender_id = opportunity.tender_id

    async with system_session() as session:
        tender = await session.get(Tender, tender_id)
        assert tender is not None
        items = list(
            (
                await session.execute(
                    select(TenderItem)
                    .where(TenderItem.tender_id == tender_id)
                    .order_by(TenderItem.item_number)
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )

    lines = [
        f"Órgão: {tender.orgao_nome}",
        f"Modalidade: {tender.modalidade}",
        f"Objeto: {tender.objeto}",
    ]
    if tender.valor_estimado is not None:
        lines.append(f"Valor estimado: R$ {tender.valor_estimado}")
    if items:
        lines.append("Itens:")
        lines.extend(f"  - Item {item.item_number}: {item.description}" for item in items)

    context = "Dados do edital:\n" + "\n".join(lines)
    evidence_refs: list[dict[str, object]] = [
        {"tender_id": str(tender_id), "item_count": len(items)}
    ]
    return context, evidence_refs


async def _handle_explain_requirement(
    *, requirement_id: uuid.UUID
) -> tuple[str, list[dict[str, object]]]:
    async with system_session() as session:
        requirement = await session.get(Requirement, requirement_id)
        if requirement is None:
            raise RequirementNotFoundError(str(requirement_id))

    context = (
        f"Requisito (categoria {requirement.category}, seção '{requirement.section}', "
        f"página {requirement.page_start}-{requirement.page_end}):\n{requirement.description}"
    )
    evidence_refs: list[dict[str, object]] = [
        {
            "requirement_id": str(requirement.id),
            "category": str(requirement.category),
            "section": requirement.section,
            "page_start": requirement.page_start,
            "page_end": requirement.page_end,
        }
    ]
    return context, evidence_refs


async def run_action(
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    action: AssistantAction,
    requirement_id: uuid.UUID | None = None,
    provider: LLMProvider | None = None,
) -> AssistantMessage:
    """Ponto de entrada unico do Assistente. `provider` e injetavel (nunca lido de
    `get_llm_provider()` implicitamente dentro dos handlers) especificamente para que os testes
    passem um `LLMProvider` falso e deterministico — nenhuma credencial de LLM real existe neste
    ambiente ainda (ver docs/phase-reports/FASE_9_REPORT.md, RISCOS)."""
    if action == AssistantAction.MISSING_REQUIREMENTS:
        context, evidence_refs = await _handle_missing_requirements(
            tenant_id=tenant_id, opportunity_id=opportunity_id
        )
    elif action == AssistantAction.UNDERSTAND_TENDER:
        context, evidence_refs = await _handle_understand_tender(opportunity_id=opportunity_id)
    elif action == AssistantAction.EXPLAIN_REQUIREMENT:
        if requirement_id is None:
            raise ValueError("EXPLAIN_REQUIREMENT exige requirement_id")
        context, evidence_refs = await _handle_explain_requirement(requirement_id=requirement_id)
    else:
        raise ValueError(f"Ação desconhecida: {action}")

    llm = provider or get_llm_provider()
    answer = await llm.complete(
        [
            LLMMessage(role=LLMRole.SYSTEM, content=_SYSTEM_PROMPT),
            LLMMessage(role=LLMRole.USER, content=context),
        ],
        max_tokens=512,
    )

    session_id = await _get_or_create_session(
        tenant_id=tenant_id, user_id=user_id, opportunity_id=opportunity_id
    )
    message = await _persist_turn(
        tenant_id=tenant_id,
        session_id=session_id,
        action=action,
        answer=answer,
        evidence_refs=evidence_refs,
    )

    assistant_actions_total.labels(action=action.value).inc()
    logger.info(
        "assistant.action_completed",
        action=action.value,
        opportunity_id=str(opportunity_id),
        evidence_count=len(evidence_refs),
    )
    return message
