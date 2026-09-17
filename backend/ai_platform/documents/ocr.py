"""OCR via Tesseract — o "um caminho de OCR" da Fase 4 (ver docs/IMPLEMENTATION_ROADMAP.md:
"nao a cadeia completa de fallback sofisticada ainda"). Sem deteccao/correcao de rotacao de
pagina e sem analise de layout de tabela — fica para um endurecimento futuro do pipeline,
documentado como limitacao conhecida (ver docs/phase-reports/FASE_4_REPORT.md).

Requer o binario do Tesseract e os arquivos de idioma (ver backend/README.md) — nao vem
embutido no ambiente Python.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
import pytesseract

from core.config import get_settings


class OcrUnavailableError(Exception):
    """Tesseract nao esta instalado/configurado neste ambiente — ver TESSERACT_CMD/TESSDATA_DIR."""


@dataclass(frozen=True)
class OcrPageResult:
    text: str
    mean_confidence: float | None  # None quando a pagina nao teve nenhuma palavra reconhecida


@dataclass(frozen=True)
class OcrResult:
    pages: list[OcrPageResult]

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages)

    @property
    def mean_confidence(self) -> float | None:
        confidences = [p.mean_confidence for p in self.pages if p.mean_confidence is not None]
        if not confidences:
            return None
        return sum(confidences) / len(confidences)


def _configure_tesseract() -> None:
    """`TESSDATA_PREFIX` e a forma que o proprio Tesseract documenta para apontar o diretorio de
    idiomas — mais robusta que passar `--tessdata-dir` como config string (que exige quoting
    correto ao atravessar o subprocess, frágil em paths do Windows com espaco/backslash)."""
    settings = get_settings()
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    if settings.tessdata_dir:
        os.environ["TESSDATA_PREFIX"] = str(Path(settings.tessdata_dir).resolve())


def ocr_pdf(content: bytes, *, render_scale: float = 2.0) -> OcrResult:
    settings = get_settings()
    _configure_tesseract()

    try:
        pdf = pdfium.PdfDocument(BytesIO(content))
    except pdfium.PdfiumError as exc:
        raise OcrUnavailableError(f"Falha ao abrir PDF para renderizacao: {exc}") from exc

    pages: list[OcrPageResult] = []
    try:
        for page in pdf:
            bitmap = page.render(scale=render_scale)
            image = bitmap.to_pil()
            try:
                data = pytesseract.image_to_data(
                    image,
                    lang=settings.ocr_language,
                    output_type=pytesseract.Output.DICT,
                )
            except pytesseract.TesseractNotFoundError as exc:
                raise OcrUnavailableError(
                    f"Tesseract nao encontrado em '{settings.tesseract_cmd}' — "
                    "ver backend/README.md para instalacao."
                ) from exc

            words = [w for w in data["text"] if w.strip()]
            confidences = [
                float(c) for c, w in zip(data["conf"], data["text"], strict=True)
                if w.strip() and float(c) >= 0
            ]
            page_text = " ".join(words)
            mean_conf = sum(confidences) / len(confidences) if confidences else None
            pages.append(OcrPageResult(text=page_text, mean_confidence=mean_conf))
    finally:
        pdf.close()

    return OcrResult(pages=pages)
