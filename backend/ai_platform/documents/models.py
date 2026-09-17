"""Document / DocumentVersion — camada de Document Intelligence (ver
docs/DATA_AND_KNOWLEDGE_ARCHITECTURE.md e docs/adr/0012-document-processing-cache.md).

`Document` e identificado por `content_hash` (GLOBAL, unico) — e a chave do Global Processing
Cache (ADR-0005): duas TenderDocument de tenants diferentes apontando para o mesmo PDF (mesmos
bytes) compartilham o mesmo `Document`, e portanto o mesmo processamento.

`DocumentVersion` NAO representa uma revisao do conteudo (isso mudaria o content_hash e seria um
`Document` diferente) — representa uma TENTATIVA DE PROCESSAMENTO daquele conteudo.
`version_number` incrementa quando o mesmo `Document` e reprocessado (ex.: pipeline melhorou,
ou reprocessamento manual apos LOW_EXTRACTION_CONFIDENCE), nunca porque os bytes mudaram.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, IdMixin, TimestampMixin


class ExtractionMethod(enum.StrEnum):
    NATIVE = "native"
    OCR = "ocr"
    VISION = "vision"
    HYBRID = "hybrid"


class ExtractionQuality(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNUSABLE = "unusable"


class LayoutQuality(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TableQuality(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOT_APPLICABLE = "not_applicable"


class Document(IdMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    latest_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DocumentVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_number"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_version: Mapped[str] = mapped_column(String(20), nullable=False)

    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        Enum(ExtractionMethod, name="extraction_method"), nullable=False
    )
    extraction_quality: Mapped[ExtractionQuality] = mapped_column(
        Enum(ExtractionQuality, name="extraction_quality"), nullable=False
    )
    ocr_required: Mapped[bool] = mapped_column(nullable=False, default=False)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    layout_quality: Mapped[LayoutQuality] = mapped_column(
        Enum(LayoutQuality, name="layout_quality"), nullable=False
    )
    table_quality: Mapped[TableQuality] = mapped_column(
        Enum(TableQuality, name="table_quality"),
        nullable=False,
        default=TableQuality.NOT_APPLICABLE,
    )

    # Estado de primeira classe (nao decorativo, ver DATA_AND_KNOWLEDGE_ARCHITECTURE.md): quando
    # true, nenhum Finding/conclusao de alto risco derivada deste texto pode ser apresentada como
    # definitiva a jusante (regra aplicada pelo consumidor — Analysis, Fase 8 — nao existe ainda,
    # mas o campo ja nasce correto para quando existir).
    low_extraction_confidence: Mapped[bool] = mapped_column(nullable=False, default=False)

    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
