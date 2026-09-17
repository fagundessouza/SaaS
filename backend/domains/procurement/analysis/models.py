"""Analysis / Finding / Evidence — dossie de uma Opportunity (Fase 8, escopo minimo: Findings +
Evidence, sem Legal/Pricing ainda, ver docs/IMPLEMENTATION_ROADMAP.md).

`Analysis` e TENANT, no maximo uma por `Opportunity` (nao um historico de versoes como Tender —
gerar de novo substitui a analise anterior, ver domains/procurement/analysis/service.py). Nunca
gerada automaticamente para toda Opportunity descoberta (ver docs/00-CRITICAL_ANALYSIS.md, item 5
da secao 6 sobre custo) — so quando o usuario aprofunda em uma oportunidade especifica.

Cada `Finding` cruza um `Requirement` do edital (Fase 6, GLOBAL) contra o que o tenant declarou
ter (`Certificate`/`Attestation`, Fase 8) e SEMPRE carrega pelo menos uma `Evidence` (DOMAIN_MODEL:
"nunca existe Finding sem pelo menos uma Evidence"). `Evidence.kind` decide qual conjunto de
campos esta preenchido: texto do proprio requisito (DocumentVersion + pagina + secao + trecho) ou
o dado estruturado do Certificate/Attestation que o tenant tem — nunca ambos por acidente.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, IdMixin, TenantScopedMixin, TimestampMixin
from domains.procurement.tenders.models import RequirementCategory


class FindingStatus(enum.StrEnum):
    MET = "met"
    MISSING = "missing"
    EXPIRED = "expired"
    # Ha Attestation/Certificate declarado, mas o match (semantico, para TECNICA) nao e confiante
    # o bastante para MET nem baixo o bastante para MISSING — precisa revisao humana. Nunca um
    # LLM decide isso sozinho (ver ADR-0007).
    NEEDS_REVIEW = "needs_review"


class FindingSeverity(enum.StrEnum):
    # Requisito de habilitacao nao atendido — bloqueia participacao se nao resolvido.
    BLOCKING = "blocking"
    # Atendimento parcial/incerto, requer atencao do usuario antes de submeter proposta.
    WARNING = "warning"
    # Ja atendido — informativo, nao exige acao.
    INFO = "info"


class EvidenceKind(enum.StrEnum):
    REQUIREMENT_TEXT = "requirement_text"
    CERTIFICATE_DATA = "certificate_data"
    ATTESTATION_DATA = "attestation_data"


class Analysis(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "analyses"
    __table_args__ = (UniqueConstraint("opportunity_id", name="uq_analyses_opportunity"),)

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=False, index=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Finding(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "findings"

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analyses.id"), nullable=False, index=True
    )
    # GLOBAL (sem RLS), referenciado de uma tabela TENANT — mesmo padrao ja usado por
    # TenderDocument.document_id (Fase 4) e Requirement.document_version_id (Fase 6): a FK e
    # legitima porque a leitura do lado GLOBAL nunca depende do tenant_scope corrente.
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id"), nullable=False, index=True
    )
    category: Mapped[RequirementCategory] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[FindingStatus] = mapped_column(
        Enum(FindingStatus, name="finding_status"), nullable=False, index=True
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        Enum(FindingSeverity, name="finding_severity"), nullable=False, index=True
    )
    # Texto explicativo curto com rotulo de forca de linguagem proporcional a evidencia
    # ("identificado", "possivel", "nao encontrado" — nunca afirmativo sem base, ver
    # DOMAIN_MODEL.md secao 14 sobre Recommendation).
    summary: Mapped[str] = mapped_column(Text, nullable=False)


class Evidence(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "evidences"

    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id"), nullable=False, index=True
    )
    kind: Mapped[EvidenceKind] = mapped_column(
        Enum(EvidenceKind, name="evidence_kind"), nullable=False
    )
    # Sempre presente, gerado deterministicamente pelo servico (nunca por um LLM) — o que torna
    # possivel auditar CADA Finding sem reabrir o documento original.
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Preenchidos quando kind == REQUIREMENT_TEXT (mesma forma de citacao do DOMAIN_MODEL:
    # DocumentVersion + pagina + secao + trecho).
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=True
    )
    section: Mapped[str | None] = mapped_column(String(200), nullable=True)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Preenchido quando kind == CERTIFICATE_DATA.
    certificate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("certificates.id"), nullable=True
    )
    # Preenchido quando kind == ATTESTATION_DATA.
    attestation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attestations.id"), nullable=True
    )
