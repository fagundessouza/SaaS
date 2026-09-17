"""CompanyProfile — perfil operacional da empresa do tenant (ver docs/DOMAIN_MODEL.md).

Um por tenant. Enriquecido automaticamente por CNPJ quando disponivel (ver cnpj_lookup.py e
service.py) — o enriquecimento e ASSINCRONO (ADR-0008): a consulta a fonte externa nunca bloqueia
o fluxo de signup.
"""

from __future__ import annotations

import enum
from typing import Any

from sqlalchemy import Enum, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, IdMixin, TenantScopedMixin, TimestampMixin


class EnrichmentStatus(enum.StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    PENDING = "pending"
    ENRICHED = "enriched"
    FAILED = "failed"


class CompanyProfile(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "company_profiles"

    cnpj: Mapped[str | None] = mapped_column(String(14), nullable=True, unique=True)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cnaes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # UFs em que a empresa aceita atuar (siglas, ex.: ["RN", "PB"]). Lista vazia = sem restricao
    # declarada de regiao — o matching trata isso como "nao filtra", nunca como "nao aceita
    # nenhuma" (ver domains/procurement/opportunities/matching.py).
    regions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # Declarados pelo usuario (Fase 7): o que a empresa vende. Sao a base tanto do filtro de
    # palavra-chave (deterministico) quanto do matching semantico (embeddings) — ver
    # domains/procurement/opportunities/matching.py e ADR-0007. Previstos no DOMAIN_MODEL desde
    # a Fase 0; viraram coluna aqui porque a Fase 7 e o primeiro consumidor real deles.
    products: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    services: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    enrichment_status: Mapped[EnrichmentStatus] = mapped_column(
        Enum(EnrichmentStatus, name="company_enrichment_status"),
        nullable=False,
        default=EnrichmentStatus.NOT_ATTEMPTED,
    )
    enrichment_error: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_enrichment: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
