"""Persistencia de Opportunity/OpportunityMatch e transicoes do ciclo de vida.

O ciclo de vida vem do DOMAIN_MODEL (secao Procurement):
    DISCOVERED -> UNDER_REVIEW -> QUALIFIED -> PURSUING -> SUBMITTED -> WON | LOST | WITHDRAWN
Transicoes sao validadas no dominio (`_ALLOWED_TRANSITIONS`), nunca so na API — o mesmo
invariante precisa valer para qualquer chamador (API, job, assistente numa fase futura).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from core.db.session import tenant_session
from core.events.publisher import publish_event
from core.observability.logging import get_logger
from core.observability.metrics import opportunities_created_total
from domains.procurement.opportunities.matching import MatchEvaluation
from domains.procurement.opportunities.models import (
    Opportunity,
    OpportunityMatch,
    OpportunityStatus,
)

logger = get_logger(__name__)

_ACTIVE_STATUSES = (
    OpportunityStatus.DISCOVERED,
    OpportunityStatus.UNDER_REVIEW,
    OpportunityStatus.QUALIFIED,
    OpportunityStatus.PURSUING,
)

_ALLOWED_TRANSITIONS: dict[OpportunityStatus, tuple[OpportunityStatus, ...]] = {
    OpportunityStatus.DISCOVERED: (OpportunityStatus.UNDER_REVIEW, OpportunityStatus.WITHDRAWN),
    OpportunityStatus.UNDER_REVIEW: (OpportunityStatus.QUALIFIED, OpportunityStatus.WITHDRAWN),
    OpportunityStatus.QUALIFIED: (OpportunityStatus.PURSUING, OpportunityStatus.WITHDRAWN),
    OpportunityStatus.PURSUING: (OpportunityStatus.SUBMITTED, OpportunityStatus.WITHDRAWN),
    # Depois de submetida a proposta, desistir nao e mais possivel — o resultado e externo
    # (ganhou/perdeu), nao uma decisao do tenant.
    OpportunityStatus.SUBMITTED: (OpportunityStatus.WON, OpportunityStatus.LOST),
    OpportunityStatus.WON: (),
    OpportunityStatus.LOST: (),
    OpportunityStatus.WITHDRAWN: (),
}


class InvalidStatusTransitionError(Exception):
    def __init__(self, current: OpportunityStatus, requested: OpportunityStatus) -> None:
        self.current = current
        self.requested = requested
        allowed = ", ".join(s.value for s in _ALLOWED_TRANSITIONS[current]) or "nenhuma"
        super().__init__(
            f"Transicao invalida de '{current.value}' para '{requested.value}'. "
            f"Transicoes permitidas a partir de '{current.value}': {allowed}."
        )


class OpportunityNotFoundError(Exception):
    pass


async def create_opportunity_from_match(
    *, tenant_id: uuid.UUID, tender_id: uuid.UUID, evaluation: MatchEvaluation
) -> uuid.UUID | None:
    """Cria a Opportunity (status DISCOVERED) + o OpportunityMatch que a justifica, e publica
    `OpportunityMatched` na mesma transacao (outbox, ADR-0004).

    Retorna None quando ja existe Opportunity deste tender para este tenant — o job de matching
    e idempotente por `(tenant_id, tender_id)` (constraint no banco), entao reavaliar o mesmo
    edital num ciclo seguinte nao duplica nem sobrescreve o workflow ja em andamento do usuario.
    """
    async with tenant_session() as session:
        existing = await session.execute(
            select(Opportunity.id).where(
                Opportunity.tenant_id == tenant_id, Opportunity.tender_id == tender_id
            )
        )
        if existing.first() is not None:
            return None

        opportunity = Opportunity(
            tenant_id=tenant_id,
            tender_id=tender_id,
            status=OpportunityStatus.DISCOVERED,
        )
        session.add(opportunity)
        await session.flush()

        session.add(
            OpportunityMatch(
                tenant_id=tenant_id,
                opportunity_id=opportunity.id,
                compatibility=evaluation.compatibility,
                confidence=evaluation.confidence,
            )
        )

        await publish_event(
            session,
            topic="OpportunityMatched",
            payload={
                "opportunity_id": str(opportunity.id),
                "tender_id": str(tender_id),
                # O evento carrega a decomposicao, nao um score unico — quem consome (notificacao,
                # auto-analise de "match forte") decide o proprio corte com os fatores na mao.
                "confidence": evaluation.confidence,
            },
            tenant_id=tenant_id,
        )

        opportunities_created_total.inc()
        logger.info(
            "opportunity.created",
            opportunity_id=str(opportunity.id),
            tender_id=str(tender_id),
            confidence=evaluation.confidence,
        )
        return opportunity.id


async def transition_status(
    *, opportunity_id: uuid.UUID, requested: OpportunityStatus
) -> Opportunity:
    async with tenant_session() as session:
        opportunity = await session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(str(opportunity_id))

        if requested not in _ALLOWED_TRANSITIONS[opportunity.status]:
            raise InvalidStatusTransitionError(opportunity.status, requested)

        previous = opportunity.status
        opportunity.status = requested
        await publish_event(
            session,
            topic="OpportunityStatusChanged",
            payload={
                "opportunity_id": str(opportunity_id),
                "from": previous.value,
                "to": requested.value,
            },
            tenant_id=opportunity.tenant_id,
        )
        logger.info(
            "opportunity.status_changed",
            opportunity_id=str(opportunity_id),
            from_status=previous.value,
            to_status=requested.value,
        )
        return opportunity


async def assign_opportunity(
    *, opportunity_id: uuid.UUID, user_id: uuid.UUID | None
) -> Opportunity:
    """Atribui (ou desatribui, com user_id=None) a Opportunity a um usuario. O RLS de `users`
    garante que um user_id de outro tenant nao seria encontrado por nenhuma query deste tenant;
    a FK garante que o id existe. Nao ha evento de dominio para isto de proposito — o catalogo
    de eventos (EVENT_AND_NOTIFICATION_ARCHITECTURE.md) nao preve notificacao de atribuicao, e
    inventar um evento sem consumidor seria complexidade sem uso.
    """
    async with tenant_session() as session:
        opportunity = await session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(str(opportunity_id))
        opportunity.assigned_to_user_id = user_id
        return opportunity


async def get_opportunity(
    opportunity_id: uuid.UUID,
) -> tuple[Opportunity, OpportunityMatch | None]:
    """Uma Opportunity especifica do tenant corrente, com o match que a justifica (se houver —
    ver docstring de OpportunityMatch sobre por que pode ser None). Escopo de tenant vem do RLS,
    mesma disciplina de `list_opportunities`."""
    async with tenant_session() as session:
        opportunity = await session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(str(opportunity_id))

        match_result = await session.execute(
            select(OpportunityMatch).where(OpportunityMatch.opportunity_id == opportunity_id)
        )
        return opportunity, match_result.scalar_one_or_none()


async def list_opportunities(
    *, status: OpportunityStatus | None = None, only_active: bool = False
) -> list[tuple[Opportunity, OpportunityMatch | None]]:
    """Lista as Opportunity do tenant corrente com o match que as justifica. O escopo de tenant
    vem do RLS (tenant_session), nunca de um filtro manual de tenant_id na query — ver ADR-0002.
    """
    async with tenant_session() as session:
        query = (
            select(Opportunity, OpportunityMatch)
            .outerjoin(OpportunityMatch, OpportunityMatch.opportunity_id == Opportunity.id)
            .order_by(Opportunity.created_at.desc())
        )
        if status is not None:
            query = query.where(Opportunity.status == status)
        elif only_active:
            query = query.where(Opportunity.status.in_(_ACTIVE_STATUSES))

        result = await session.execute(query)
        return [(row[0], row[1]) for row in result.all()]
