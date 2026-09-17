"""Tender — edital publicado. GLOBAL por definicao (ver docs/DOMAIN_MODEL.md): e informacao
publica, sem tenant_id, sem RLS. Versionado porque editais sofrem retificacao — uma mudanca
NUNCA sobrescreve TenderVersion.raw_payload, sempre cria uma nova linha (ver
domains/procurement/tenders/service.py e docs/adr/0009-pncp-fonte-canonica.md).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
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
