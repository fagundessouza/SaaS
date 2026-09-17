"""get_or_process_document contra Postgres real: caminho nativo, caminho OCR, e reaproveitamento
do Global Processing Cache por content_hash (ver ai_platform/documents/service.py e ADR-0012).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from ai_platform.documents.models import DocumentVersion, ExtractionMethod, ExtractionQuality
from ai_platform.documents.service import get_or_process_document
from core.config import get_settings
from core.db.session import system_session
from tests.conftest import unique_text
from tests.pdf_fixtures import make_corrupted_pdf, make_image_only_pdf, make_native_text_pdf


def _long_text(marker: str) -> str:
    return (
        f"Edital de Pregao Eletronico numero 001/2026 {marker}. Objeto: aquisicao de materiais "
        "de escritorio para a Secretaria de Administracao do Municipio Exemplo, incluindo papel, "
        "canetas, grampeadores e demais itens de consumo necessarios ao funcionamento regular "
        "das unidades administrativas, conforme especificacoes detalhadas no Termo de Referencia."
    )


def _tesseract_available() -> bool:
    cmd = get_settings().tesseract_cmd
    return shutil.which(cmd) is not None or Path(cmd).exists()


async def test_process_native_text_pdf_is_classified_correctly() -> None:
    pdf_bytes = make_native_text_pdf(_long_text(unique_text("classify")))

    result = await get_or_process_document(pdf_bytes)

    assert result.reused_cache is False
    assert result.extraction_quality in (ExtractionQuality.HIGH, ExtractionQuality.MEDIUM)

    async with system_session() as session:
        version = await session.get(DocumentVersion, result.document_version_id)
        assert version is not None
        assert version.extraction_method == ExtractionMethod.NATIVE
        assert version.ocr_required is False
        assert version.low_extraction_confidence is False
        assert "Pregao Eletronico" in version.extracted_text


async def test_process_same_content_twice_reuses_cache() -> None:
    pdf_bytes = make_native_text_pdf(_long_text(unique_text("cache-reuse")))

    first = await get_or_process_document(pdf_bytes)
    second = await get_or_process_document(pdf_bytes)

    assert first.reused_cache is False
    assert second.reused_cache is True
    assert first.document_id == second.document_id
    assert first.document_version_id == second.document_version_id

    async with system_session() as session:
        versions = (
            await session.execute(
                select(DocumentVersion).where(DocumentVersion.document_id == first.document_id)
            )
        ).scalars().all()
        assert len(versions) == 1  # nao reprocessou


async def test_corrupted_pdf_is_marked_unusable_without_raising() -> None:
    result = await get_or_process_document(make_corrupted_pdf())

    assert result.extraction_quality == ExtractionQuality.UNUSABLE

    async with system_session() as session:
        version = await session.get(DocumentVersion, result.document_version_id)
        assert version is not None
        assert version.low_extraction_confidence is True


@pytest.mark.skipif(
    not _tesseract_available(), reason="Tesseract nao encontrado (ver TESSERACT_CMD no .env)"
)
async def test_process_image_only_pdf_falls_back_to_ocr() -> None:
    pdf_bytes = make_image_only_pdf(
        unique_text("Aviso de licitacao numero 042 barra 2026 pregao eletronico")
    )

    result = await get_or_process_document(pdf_bytes)

    async with system_session() as session:
        version = await session.get(DocumentVersion, result.document_version_id)
        assert version is not None
        assert version.extraction_method == ExtractionMethod.OCR
        assert version.ocr_required is True
        assert version.ocr_confidence is not None
        assert "licitacao" in version.extracted_text.lower()
        # OCR nunca e classificado HIGH, mesmo com confianca alta (ver service.py _classify_ocr)
        assert version.extraction_quality != ExtractionQuality.HIGH
