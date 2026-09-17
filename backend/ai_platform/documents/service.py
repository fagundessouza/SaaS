"""Orquestra o Document Intelligence: dado o conteudo bruto de um documento, decide
nativo-vs-OCR, calcula a qualidade de extracao (nunca hardcoded — sempre derivada de uma
metrica real, ver quality.py/ocr.py) e persiste como DocumentVersion.

Aplica o Global Processing Cache (ADR-0005/ADR-0012): se o `Document` deste content_hash ja tem
uma DocumentVersion processada pela versao atual do pipeline, reaproveita — nao reprocessa.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from ai_platform.documents.models import (
    Document,
    DocumentVersion,
    ExtractionMethod,
    ExtractionQuality,
    LayoutQuality,
    TableQuality,
)
from ai_platform.documents.ocr import OcrUnavailableError, ocr_pdf
from ai_platform.documents.quality import UnreadablePdfError, assess_native_quality
from core.db.session import system_session
from core.observability.logging import get_logger
from core.observability.metrics import (
    document_processing_cache_hits_total,
    document_processing_duration_seconds,
    document_processing_total,
)

logger = get_logger(__name__)

# Incrementar sempre que a logica de extracao/classificacao de qualidade mudar de forma que
# justifique reprocessar documentos ja processados (ver get_or_process_document).
PROCESSING_VERSION = "v1"

_OCR_MEDIUM_CONFIDENCE_THRESHOLD = 70.0
_OCR_LOW_CONFIDENCE_THRESHOLD = 40.0
_OCR_MIN_TEXT_LENGTH = 20


def compute_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class ProcessingResult:
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    extraction_quality: ExtractionQuality
    reused_cache: bool


def _classify_native(avg_chars_per_page: float) -> ExtractionQuality:
    if avg_chars_per_page >= 300:
        return ExtractionQuality.HIGH
    return ExtractionQuality.MEDIUM


def _classify_ocr(text: str, mean_confidence: float | None) -> ExtractionQuality:
    if mean_confidence is None or len(text.strip()) < _OCR_MIN_TEXT_LENGTH:
        return ExtractionQuality.UNUSABLE
    if mean_confidence >= _OCR_MEDIUM_CONFIDENCE_THRESHOLD:
        # Nunca HIGH para OCR: mesmo confiante, OCR e menos confiavel que texto nativo (ver
        # docs/00-CRITICAL_ANALYSIS.md sobre nunca transformar OCR em falsa certeza).
        return ExtractionQuality.MEDIUM
    if mean_confidence >= _OCR_LOW_CONFIDENCE_THRESHOLD:
        return ExtractionQuality.LOW
    return ExtractionQuality.UNUSABLE


async def get_or_process_document(content: bytes) -> ProcessingResult:
    content_hash = compute_content_hash(content)

    async with system_session() as session:
        result = await session.execute(
            select(Document).where(Document.content_hash == content_hash)
        )
        document = result.scalar_one_or_none()

        if document is not None:
            existing_version = await session.execute(
                select(DocumentVersion)
                .where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.processing_version == PROCESSING_VERSION,
                )
                .order_by(DocumentVersion.version_number.desc())
                .limit(1)
            )
            cached = existing_version.scalar_one_or_none()
            if cached is not None:
                document_processing_cache_hits_total.inc()
                logger.info("document.cache_hit", content_hash=content_hash)
                return ProcessingResult(
                    document_id=document.id,
                    document_version_id=cached.id,
                    extraction_quality=cached.extraction_quality,
                    reused_cache=True,
                )
        else:
            document = Document(content_hash=content_hash, latest_version_number=0)
            session.add(document)
            await session.flush()

        document_id = document.id
        next_version_number = document.latest_version_number + 1

    started_at = time.monotonic()
    method, quality, ocr_required, ocr_confidence, page_count, text, diagnostics = _extract(
        content
    )
    duration = time.monotonic() - started_at

    is_low_confidence = quality in (ExtractionQuality.LOW, ExtractionQuality.UNUSABLE)
    if method == ExtractionMethod.NATIVE:
        layout_quality = LayoutQuality.HIGH
    elif not is_low_confidence:
        layout_quality = LayoutQuality.MEDIUM
    else:
        layout_quality = LayoutQuality.LOW

    async with system_session() as session:
        document = await session.get(Document, document_id)
        assert document is not None

        version = DocumentVersion(
            document_id=document_id,
            version_number=next_version_number,
            processing_version=PROCESSING_VERSION,
            extraction_method=method,
            extraction_quality=quality,
            ocr_required=ocr_required,
            ocr_confidence=ocr_confidence,
            layout_quality=layout_quality,
            table_quality=TableQuality.NOT_APPLICABLE,
            low_extraction_confidence=is_low_confidence,
            page_count=page_count,
            extracted_text=text,
            diagnostics=diagnostics,
        )
        session.add(version)
        document.latest_version_number = next_version_number
        await session.flush()
        version_id = version.id

    document_processing_total.labels(method=method.value, quality=quality.value).inc()
    document_processing_duration_seconds.labels(method=method.value).observe(duration)
    logger.info(
        "document.processed",
        content_hash=content_hash,
        method=method.value,
        quality=quality.value,
        duration_s=round(duration, 2),
    )

    return ProcessingResult(
        document_id=document_id,
        document_version_id=version_id,
        extraction_quality=quality,
        reused_cache=False,
    )


def _extract(
    content: bytes,
) -> tuple[ExtractionMethod, ExtractionQuality, bool, float | None, int, str, dict[str, Any]]:
    try:
        native = assess_native_quality(content)
    except UnreadablePdfError as exc:
        return (
            ExtractionMethod.NATIVE,
            ExtractionQuality.UNUSABLE,
            False,
            None,
            0,
            "",
            {"error": str(exc)},
        )

    if native.native_text_sufficient:
        text = "\n\n".join(native.text_by_page)
        quality = _classify_native(native.avg_chars_per_page)
        return (
            ExtractionMethod.NATIVE,
            quality,
            False,
            None,
            native.page_count,
            text,
            {"avg_chars_per_page": native.avg_chars_per_page},
        )

    try:
        ocr_result = ocr_pdf(content)
    except OcrUnavailableError as exc:
        logger.error("document.ocr_unavailable", error=str(exc))
        return (
            ExtractionMethod.OCR,
            ExtractionQuality.UNUSABLE,
            True,
            None,
            native.page_count,
            "",
            {"avg_chars_per_page": native.avg_chars_per_page, "ocr_error": str(exc)},
        )

    quality = _classify_ocr(ocr_result.text, ocr_result.mean_confidence)
    return (
        ExtractionMethod.OCR,
        quality,
        True,
        ocr_result.mean_confidence,
        len(ocr_result.pages),
        ocr_result.text,
        {
            "avg_chars_per_page": native.avg_chars_per_page,
            "ocr_mean_confidence": ocr_result.mean_confidence,
        },
    )
