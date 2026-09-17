"""Geracao de PDFs reais para testes de Document Intelligence — nao mocka nem quality.py nem
ocr.py, gera bytes de PDF de verdade (via fpdf2) para exercitar os dois caminhos genuinamente:
um com camada de texto nativa, outro so-imagem (simula documento escaneado sem OCR embutido).
"""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from fpdf import FPDF
from PIL import Image, ImageDraw


def make_native_text_pdf(text: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.multi_cell(0, 10, text)
    return bytes(pdf.output())


def make_image_only_pdf(text: str, *, image_size: tuple[int, int] = (900, 200)) -> bytes:
    """PDF sem nenhuma camada de texto extraivel via pypdf — so uma imagem com texto renderizado,
    exatamente o cenario que deve acionar o caminho de OCR."""
    with NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        image = Image.new("RGB", image_size, color="white")
        draw = ImageDraw.Draw(image)
        draw.text((10, image_size[1] // 2 - 10), text, fill="black")
        image.save(tmp_path)

        pdf = FPDF()
        pdf.add_page()
        pdf.image(str(tmp_path), x=0, y=0, w=210)
        return bytes(pdf.output())
    finally:
        tmp_path.unlink(missing_ok=True)


def make_corrupted_pdf() -> bytes:
    return b"isto nao e um PDF valido, so bytes aleatorios"
