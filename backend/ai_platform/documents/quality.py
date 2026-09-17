"""Deteccao de qualidade da camada de texto nativa de um PDF — decide se a extracao estrutural
(pypdf) e suficiente ou se e preciso cair para OCR (ver ai_platform/documents/service.py).

O limiar abaixo (`_MIN_CHARS_PER_PAGE_FOR_NATIVE`) e uma heuristica documentada, nao um numero
magico: PDFs nativamente digitados tipicamente tem centenas de caracteres por pagina; um PDF
escaneado sem OCR embutido tem zero ou quase zero (só o que a camada de metadado eventualmente
carrega). Nao ha OCR real embutido nesta deteccao — so pypdf, por isso e barato rodar em todo
documento antes de decidir se vale a pena pagar o custo de renderizar+OCRizar.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

_MIN_CHARS_PER_PAGE_FOR_NATIVE = 100
_MIN_CHARS_PER_PAGE_FOR_HIGH_QUALITY = 300


@dataclass(frozen=True)
class NativeQualityAssessment:
    page_count: int
    avg_chars_per_page: float
    native_text_sufficient: bool
    text_by_page: list[str]


class UnreadablePdfError(Exception):
    """O arquivo nao pode nem ser aberto como PDF — corrompido ou nao e um PDF de verdade."""


def assess_native_quality(content: bytes) -> NativeQualityAssessment:
    try:
        reader = PdfReader(BytesIO(content))
        page_count = len(reader.pages)
        text_by_page = [page.extract_text() or "" for page in reader.pages]
    except (PdfReadError, ValueError) as exc:
        raise UnreadablePdfError(str(exc)) from exc

    if page_count == 0:
        return NativeQualityAssessment(0, 0.0, False, [])

    total_chars = sum(len(text.strip()) for text in text_by_page)
    avg_chars_per_page = total_chars / page_count

    return NativeQualityAssessment(
        page_count=page_count,
        avg_chars_per_page=avg_chars_per_page,
        native_text_sufficient=avg_chars_per_page >= _MIN_CHARS_PER_PAGE_FOR_NATIVE,
        text_by_page=text_by_page,
    )
