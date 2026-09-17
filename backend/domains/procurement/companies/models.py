"""CompanyProfile — perfil operacional da empresa do tenant (ver docs/DOMAIN_MODEL.md).

Um por tenant. Enriquecido automaticamente por CNPJ quando disponivel (ver cnpj_lookup.py e
service.py) — o enriquecimento e ASSINCRONO (ADR-0008): a consulta a fonte externa nunca bloqueia
o fluxo de signup.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, IdMixin, TenantScopedMixin, TimestampMixin
from domains.procurement.tenders.models import RequirementCategory


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


class Certificate(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    """Certidao (fiscal, trabalhista, jurídica, econômico-financeira) que o tenant declara ter —
    entrada manual nesta fase (Fase 8), sem verificação automática contra fonte externa (ver
    docs/phase-reports/FASE_8_REPORT.md, DECISÕES: `CertificateValidationLog`/verificação
    externa da seção 10K do prompt mestre ficam para quando houver fonte real a integrar).

    `category` reaproveita `RequirementCategory` (Fase 6) de propósito — é a mesma taxonomia que
    `Requirement.category`, o que é o que permite `domains/procurement/analysis/service.py`
    cruzar um requisito de habilitação com a certidão que o atende sem uma segunda tabela de
    mapeamento entre vocabulários.

    `status` NÃO é uma coluna persistida: é sempre derivado de `expires_at` comparado à data
    corrente no momento da análise (regra determinística, ADR-0007 — "prazos, comparação de
    datas") — uma coluna persistida ficaria desatualizada sem um job de recomputação que nada
    aqui justifica ainda.
    """

    __tablename__ = "certificates"

    company_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company_profiles.id"), nullable=False, index=True
    )
    category: Mapped[RequirementCategory] = mapped_column(String(30), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    issued_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # None = sem data de vencimento (ex.: contrato social nao expira) — tratado como sempre
    # valido, nunca como "vencido por falta de dado" (ver analysis/service.py).
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Attestation(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    """Atestado de capacidade técnica — evidência de experiência anterior que o tenant declara
    ter, usada para cruzar contra requisitos de categoria `TECNICA` (ver
    domains/procurement/analysis/service.py). Ao contrário de `Certificate`, não tem um estado
    binário válido/vencido: a presença e a relevância semântica do `object_description` frente
    ao requisito é que determinam o Finding.
    """

    __tablename__ = "attestations"

    company_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company_profiles.id"), nullable=False, index=True
    )
    issuing_org: Mapped[str] = mapped_column(String(255), nullable=False)
    object_description: Mapped[str] = mapped_column(Text, nullable=False)
    contract_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
