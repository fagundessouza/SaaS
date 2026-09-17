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
    regions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    enrichment_status: Mapped[EnrichmentStatus] = mapped_column(
        Enum(EnrichmentStatus, name="company_enrichment_status"),
        nullable=False,
        default=EnrichmentStatus.NOT_ATTEMPTED,
    )
    enrichment_error: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_enrichment: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
