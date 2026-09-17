"""Testa OCR de verdade (Tesseract real, sem mock) — ver ai_platform/documents/ocr.py.

Pulado quando o Tesseract nao esta instalado/configurado neste ambiente (ver
backend/README.md), em vez de falhar — a suite continua util em uma maquina sem Tesseract, mas
CI instala o binario (ver .github/workflows/ci.yml) para que isto rode de verdade la.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ai_platform.documents.ocr import ocr_pdf
from core.config import get_settings
from tests.pdf_fixtures import make_image_only_pdf


def _tesseract_available() -> bool:
    cmd = get_settings().tesseract_cmd
    return shutil.which(cmd) is not None or Path(cmd).exists()


pytestmark = pytest.mark.skipif(
    not _tesseract_available(), reason="Tesseract nao encontrado (ver TESSERACT_CMD no .env)"
)


def test_ocr_extracts_text_from_scanned_looking_pdf() -> None:
    pdf_bytes = make_image_only_pdf("Aviso de licitacao numero 042 barra 2026")

    result = ocr_pdf(pdf_bytes)

    assert "licitacao" in result.text.lower()
    assert result.mean_confidence is not None
    assert result.mean_confidence > 50


def test_ocr_on_blank_page_has_no_confident_text() -> None:
    pdf_bytes = make_image_only_pdf("")

    result = ocr_pdf(pdf_bytes)

    assert result.text.strip() == ""
