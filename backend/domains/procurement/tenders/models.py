"""Tender — edital publicado. GLOBAL por definicao (ver docs/DOMAIN_MODEL.md): e informacao
publica, sem tenant_id, sem RLS. Versionado porque editais sofrem retificacao — uma mudanca
NUNCA sobrescreve TenderVersion.raw_payload, sempre cria uma nova linha (ver
domains/procurement/tenders/service.py e docs/adr/0009-pncp-fonte-canonica.md).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, IdMixin, TimestampMixin


class Tender(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenders"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_tenders_source_external_id"),
    )

    source: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)

    orgao_cnpj: Mapped[str] = mapped_column(String(14), nullable=False, index=True)
    orgao_nome: Mapped[str] = mapped_column(String(255), nullable=False)
    unidade_nome: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Adicionados na Fase 7 (correcao retroativa, ver FASE_7_REPORT): o filtro deterministico de
    # regiao do Opportunity Engine precisa de UF comparavel; antes disso o dado existia apenas
    # dentro de TenderVersion.raw_payload (JSONB), inutilizavel para filtro indexado. Nullable
    # porque a fonte pode omitir (e porque as linhas ja ingeridas antes da migration podem nao
    # ter o campo no payload).
    uf: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    municipio: Mapped[str | None] = mapped_column(String(120), nullable=True)

    modalidade: Mapped[str] = mapped_column(String(60), nullable=False)
    objeto: Mapped[str] = mapped_column(Text, nullable=False)
    valor_estimado: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    data_publicacao: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_abertura_proposta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    data_encerramento_proposta: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    situacao: Mapped[str | None] = mapped_column(String(60), nullable=True)

    latest_version_number: Mapped[int] = mapped_column(nullable=False, default=1)


class TenderVersion(IdMixin, TimestampMixin, Base):
    """Uma linha por retificacao/reingestao com conteudo diferente. `content_hash` e o que
    decide se uma nova versao e criada (ver service.py) — nunca comparamos campo a campo.
    """

    __tablename__ = "tender_versions"
    __table_args__ = (
        UniqueConstraint("tender_id", "version_number", name="uq_tender_versions_number"),
        UniqueConstraint("tender_id", "content_hash", name="uq_tender_versions_hash"),
    )

    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class TenderDocument(IdMixin, TimestampMixin, Base):
    """Anexo do edital: referencia + bytes brutos em MinIO + (a partir da Fase 4) o resultado do
    Document Intelligence via `document_id` (ver ai_platform/documents/models.py e
    docs/adr/0012-document-processing-cache.md). `document_id` fica nulo ate o processamento
    completar — e o que permite `TenderDocument`s de tenders diferentes apontando para o mesmo
    PDF (mesmo content_hash) compartilharem o mesmo `Document` processado uma unica vez.
    """

    __tablename__ = "tender_documents"
    __table_args__ = (
        UniqueConstraint(
            "tender_id", "external_document_id", name="uq_tender_documents_external_id"
        ),
    )

    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False, index=True
    )
    external_document_id: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    download_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TenderItem(IdMixin, TimestampMixin, Base):
    """Item/lote de um Tender (Fase 6). GLOBAL como o proprio Tender — extraido por regra
    deterministica (sem IA: o PNCP ja entrega item estruturado, ver
    ingestion/connectors/pncp.py `fetch_items`/`_parse_item`, ADR-0007). Nao versionado por
    retificacao como TenderVersion — uma retificacao de item reingesta e faz upsert por
    `(tender_id, item_number)`, ver domains/procurement/tenders/items_service.py.
    """

    __tablename__ = "tender_items"
    __table_args__ = (
        UniqueConstraint("tender_id", "item_number", name="uq_tender_items_item_number"),
    )

    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False, index=True
    )
    item_number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    material_or_service: Mapped[str | None] = mapped_column(String(30), nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    unit_of_measure: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # None (nao 0) quando o orgao marcou orcamento sigiloso — ver _parse_item.
    unit_estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_estimated_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class RequirementCategory(enum.StrEnum):
    FISCAL = "fiscal"
    TECNICA = "tecnica"
    ECONOMICO_FINANCEIRA = "economico_financeira"
    JURIDICA = "juridica"


class Requirement(IdMixin, TimestampMixin, Base):
    """Requisito de habilitacao extraido do texto do edital (Fase 6). GLOBAL como o Tender.

    Extracao em duas etapas (ADR-0007, "IA assistindo regra"), espelhando o chunking da Fase 5:
    1. REGRA: candidatos sao chunks do tipo `clause` (ver ai_platform/chunking) cujo cabecalho
       de secao bate com vocabulario conhecido de habilitacao ("DA HABILITACAO", "QUALIFICACAO
       TECNICA" etc. — ver domains/procurement/tenders/requirements_service.py).
    2. IA: cada candidato e classificado em `RequirementCategory` por similaridade de embedding
       contra um texto-prototipo por categoria (mesmo EmbeddingProvider self-hosted da Fase 5,
       sem LLM generativo novo — ver DECISOES do relatorio da Fase 6). `confidence` e o cosseno
       da categoria vencedora, nao uma probabilidade calibrada.

    `document_version_id` + `page_start`/`page_end` + `section` sao a evidencia (mesmo padrao
    de `Evidence` do DOMAIN_MODEL: sempre aponta para DocumentVersion + pagina + secao).
    Idempotente por `(document_version_id, chunk_index)` — chunking e uma funcao pura de
    `page_texts`, entao o mesmo chunk sempre tem o mesmo indice para a mesma versao.
    """

    __tablename__ = "requirements"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id", "chunk_index", name="uq_requirements_document_chunk"
        ),
    )

    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id"), nullable=False, index=True
    )
    category: Mapped[RequirementCategory] = mapped_column(String(30), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str | None] = mapped_column(String(200), nullable=True)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
