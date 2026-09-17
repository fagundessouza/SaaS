"""Chunking estrutural de editais brasileiros (ver docs/DATA_AND_KNOWLEDGE_ARCHITECTURE.md).

Duas etapas, como documentado na Fase 0:
1. Segmentacao por estrutura conhecida: detecta cabecalhos de secoes tipicas de edital
   (heuristica de vocabulario + padrao numerado). Se nenhuma secao for detectada, cai para
   fallback (documento inteiro tratado como uma unica secao "preambulo") — NAO tenta
   segmentacao semantica sofisticada aqui (fora do "escopo minimo" desta fase).
2. Sub-chunking dentro de cada secao, por paragrafo, empacotado ate um teto de caracteres,
   nunca cruzando fronteira de secao.

Limitacoes conhecidas (documentadas, nao escondidas — ver docs/phase-reports/FASE_5_REPORT.md):
apenas um nivel de secao (sem sub-secoes aninhadas tipo "8.2 dentro de 8"), e sem deteccao real
de tabela/lista (`chunk_type` so distingue `preamble` de `clause`).
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

_MAX_CHUNK_CHARS = 1200

_KNOWN_SECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"pre[aâ]mbulo",
        r"do objeto\b|^objeto$",
        r"condi[cç][oõ]es de participa[cç][aã]o",
        r"da habilita[cç][aã]o",
        r"qualifica[cç][aã]o t[eé]cnica",
        r"qualifica[cç][aã]o econ[oô]mico.?financeira",
        r"regularidade fiscal|requisitos fiscais",
        r"do julgamento|crit[eé]rios? de julgamento",
        r"da proposta",
        r"dos? pre[cç]os?",
        r"das? san[cç][oõ]es|penalidades",
        r"dos? recursos?|impugna[cç][aã]o",
        r"dos? prazos?",
        r"das? obriga[cç][oõ]es",
        r"execu[cç][aã]o (do )?contrat",
        r"do pagamento",
        r"das? garantias?",
        r"dos? anexos?|^anexo\b",
        r"termo de refer[eê]ncia",
        r"estudo t[eé]cnico preliminar",
        r"matriz de riscos",
    ]
]

_NUMBER_PREFIX = re.compile(
    r"^\s*(\d+(\.\d+)*\.?|cl[aá]usula\s+\w+|se[cç][aã]o\s+\w+)\s*", re.IGNORECASE
)
_HEADING_MAX_LEN = 100
_MIN_UPPERCASE_RATIO = 0.7


class ChunkType(enum.StrEnum):
    PREAMBLE = "preamble"
    CLAUSE = "clause"


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    section: str | None
    heading_path: list[str]
    chunk_type: ChunkType
    page_start: int
    page_end: int
    content: str


def _is_mostly_uppercase(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return (upper / len(letters)) >= _MIN_UPPERCASE_RATIO


def _is_heading(line: str) -> bool:
    """Cabecalho = bate com vocabulario conhecido de edital E parece um titulo curto (maioria
    maiuscula apos remover um eventual prefixo numerado) — so o vocabulario sozinho marcaria
    qualquer clausula que mencione, por exemplo, "regularidade fiscal" no meio de uma frase
    como se fosse um cabecalho novo. Ver limitacoes no topo do modulo.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > _HEADING_MAX_LEN:
        return False
    if not any(pattern.search(stripped) for pattern in _KNOWN_SECTION_PATTERNS):
        return False
    without_prefix = _NUMBER_PREFIX.sub("", stripped).strip()
    return _is_mostly_uppercase(without_prefix)


@dataclass
class _Segment:
    heading: str | None
    lines: list[tuple[int, str]]


def _segment_by_heading(lines_with_page: list[tuple[int, str]]) -> list[_Segment]:
    segments: list[_Segment] = []
    current_heading: str | None = None
    current_lines: list[tuple[int, str]] = []

    for page, line in lines_with_page:
        if _is_heading(line):
            if current_lines:
                segments.append(_Segment(current_heading, current_lines))
            current_heading = line.strip()
            current_lines = []
        current_lines.append((page, line))

    if current_lines:
        segments.append(_Segment(current_heading, current_lines))

    return segments


def _split_into_paragraphs(lines: list[tuple[int, str]]) -> list[tuple[int, int, str]]:
    paragraphs: list[tuple[int, int, str]] = []
    buf: list[tuple[int, str]] = []

    def _flush(buf: list[tuple[int, str]]) -> None:
        if not buf:
            return
        text = "\n".join(line for _, line in buf).strip()
        if text:
            pages = [page for page, _ in buf]
            paragraphs.append((min(pages), max(pages), text))

    for page, line in lines:
        if line.strip():
            buf.append((page, line))
        else:
            _flush(buf)
            buf = []
    _flush(buf)

    return paragraphs


@dataclass(frozen=True)
class _PackedChunk:
    text: str
    page_start: int
    page_end: int


def _pack_paragraphs(lines: list[tuple[int, str]]) -> list[_PackedChunk]:
    paragraphs = _split_into_paragraphs(lines)
    if not paragraphs:
        return []

    chunks: list[_PackedChunk] = []
    current_texts: list[str] = []
    current_start = paragraphs[0][0]
    current_end = paragraphs[0][1]
    current_len = 0

    for p_start, p_end, text in paragraphs:
        if current_texts and current_len + len(text) > _MAX_CHUNK_CHARS:
            chunks.append(_PackedChunk("\n\n".join(current_texts), current_start, current_end))
            current_texts = []
            current_len = 0

        if len(text) > _MAX_CHUNK_CHARS:
            # Paragrafo sozinho maior que o teto: corte bruto por tamanho — heuristica minima,
            # nao tenta achar um ponto de corte "elegante" (ver limitacoes no topo do modulo).
            if current_texts:
                chunks.append(
                    _PackedChunk("\n\n".join(current_texts), current_start, current_end)
                )
                current_texts = []
                current_len = 0
            for i in range(0, len(text), _MAX_CHUNK_CHARS):
                chunks.append(_PackedChunk(text[i : i + _MAX_CHUNK_CHARS], p_start, p_end))
            continue

        if not current_texts:
            current_start = p_start
        current_texts.append(text)
        current_end = p_end
        current_len += len(text)

    if current_texts:
        chunks.append(_PackedChunk("\n\n".join(current_texts), current_start, current_end))

    return chunks


def chunk_document(page_texts: list[str]) -> list[Chunk]:
    lines_with_page = [
        (page_number, line)
        for page_number, page_text in enumerate(page_texts, start=1)
        for line in page_text.splitlines()
    ]

    if not any(line.strip() for _, line in lines_with_page):
        return []

    segments = _segment_by_heading(lines_with_page)

    chunks: list[Chunk] = []
    chunk_index = 0
    for segment in segments:
        chunk_type = ChunkType.PREAMBLE if segment.heading is None else ChunkType.CLAUSE
        heading_path = [segment.heading] if segment.heading else []

        for packed in _pack_paragraphs(segment.lines):
            chunks.append(
                Chunk(
                    chunk_index=chunk_index,
                    section=segment.heading,
                    heading_path=heading_path,
                    chunk_type=chunk_type,
                    page_start=packed.page_start,
                    page_end=packed.page_end,
                    content=packed.text,
                )
            )
            chunk_index += 1

    return chunks
