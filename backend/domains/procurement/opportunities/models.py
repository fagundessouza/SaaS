"""Opportunity — a lente de um Tender (GLOBAL) pelos olhos de um tenant especifico (TENANT).

O mesmo edital gera N Opportunity diferentes, uma por tenant, cada uma com seu proprio ciclo de
vida de workflow — nao confundir os dois agregados (ver docs/DOMAIN_MODEL.md, secao Procurement,
e docs/00-CRITICAL_ANALYSIS.md secao 8 item 2).
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, IdMixin, TenantScopedMixin, TimestampMixin


class OpportunityStatus(enum.StrEnum):
    DISCOVERED = "discovered"
    UNDER_REVIEW = "under_review"
    QUALIFIED = "qualified"
    PURSUING = "pursuing"
    SUBMITTED = "submitted"
    WON = "won"
    LOST = "lost"
    WITHDRAWN = "withdrawn"


class Opportunity(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        # Um edital gera no maximo uma Opportunity por tenant — e o que torna o job de matching
        # idempotente sem precisar de marcador de "ja avaliado" em nenhuma outra tabela.
        UniqueConstraint("tenant_id", "tender_id", name="uq_opportunities_tenant_tender"),
    )

    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False, index=True
    )
    status: Mapped[OpportunityStatus] = mapped_column(
        Enum(OpportunityStatus, name="opportunity_status"),
        nullable=False,
        default=OpportunityStatus.DISCOVERED,
        index=True,
    )
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class OpportunityMatch(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    """O *porque* de uma Opportunity existir: quais criterios bateram, com que evidencia e com
    que confianca por tecnica usada.

    `compatibility` e `confidence` sao deliberadamente JSONB decompostos por criterio, e NAO
    existe nenhuma coluna de "score final": um numero unico de compatibilidade sem decomposicao
    e classificado explicitamente como risco de "Fake AI" na analise critica da Fase 0 (ver
    docs/00-CRITICAL_ANALYSIS.md, item 5 da tabela de ambiguidades e a linha "Score unico de
    compatibilidade sem decomposicao" da tabela de vereditos). Quem consome decide como
    apresentar; o dominio nunca funde criterio deterministico com score de modelo.

    Formato de `compatibility` (uma chave por criterio avaliado):
        {"region": {"matched": true, "tender_uf": "RN", "profile_regions": ["RN"]},
         "keyword": {"matched": true, "matched_terms": ["material de escritorio"]},
         "semantic": {"matched": true, "best_term": "canetas", "score": 0.71,
                      "threshold": 0.45}}

    Formato de `confidence` (confianca DA TECNICA por criterio, nao probabilidade de ganhar a
    licitacao): deterministico = 1.0, semantico = score do modelo.
        {"region": 1.0, "keyword": 1.0, "semantic": 0.71}

    TENANT (com tenant_id + RLS) apesar de ser DERIVADA de Opportunity no DOMAIN_MODEL: defesa
    em profundidade, conforme SECURITY_MODEL ("tenant_id obrigatorio em toda tabela TENANT" +
    RLS como segunda barreira) — um bug de join nao vaza match entre tenants. Ver DECISOES do
    relatorio da Fase 7.
    """

    __tablename__ = "opportunity_matches"
    __table_args__ = (
        UniqueConstraint("opportunity_id", name="uq_opportunity_matches_opportunity"),
    )

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=False, index=True
    )
    compatibility: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False, default=dict)
