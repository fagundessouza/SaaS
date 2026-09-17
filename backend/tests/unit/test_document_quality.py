from __future__ import annotations

import pytest

from ai_platform.documents.quality import UnreadablePdfError, assess_native_quality
from tests.pdf_fixtures import make_corrupted_pdf, make_image_only_pdf, make_native_text_pdf

_LONG_TEXT = (
    "Edital de Pregao Eletronico numero 001/2026. Objeto: aquisicao de materiais de "
    "escritorio para a Secretaria de Administracao do Municipio Exemplo, incluindo papel, "
    "canetas, grampeadores e demais itens de consumo necessarios ao funcionamento regular "
    "das unidades administrativas, conforme especificacoes detalhadas no Termo de Referencia "
    "anexo a este instrumento convocatorio, observadas as disposicoes da Lei 14.133/2021."
)


def test_native_text_pdf_is_assessed_as_sufficient() -> None:
    pdf_bytes = make_native_text_pdf(_LONG_TEXT)

    result = assess_native_quality(pdf_bytes)

    assert result.page_count == 1
    assert result.native_text_sufficient is True
    assert result.avg_chars_per_page > 100
    assert "Pregao Eletronico" in result.text_by_page[0]


def test_image_only_pdf_is_assessed_as_insufficient() -> None:
    pdf_bytes = make_image_only_pdf("Edital escaneado sem camada de texto")

    result = assess_native_quality(pdf_bytes)

    assert result.page_count == 1
    assert result.native_text_sufficient is False
    assert result.avg_chars_per_page < 5


def test_corrupted_pdf_raises_unreadable_error() -> None:
    with pytest.raises(UnreadablePdfError):
        assess_native_quality(make_corrupted_pdf())
