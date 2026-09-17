from __future__ import annotations

from ai_platform.chunking.chunker import ChunkType, chunk_document

_PAGE_1 = """EDITAL DE PREGAO ELETRONICO N. 001/2026

PREAMBULO

O Municipio Exemplo torna publico que realizara licitacao na modalidade Pregao Eletronico.

1. DO OBJETO

1.1. O presente edital tem por objeto a aquisicao de materiais de escritorio, conforme \
especificacoes do Anexo I.

1.2. Os itens deverao ser entregues no prazo de 30 dias.

2. DAS CONDICOES DE PARTICIPACAO

2.1. Poderao participar desta licitacao empresas do ramo pertinente ao objeto.
2.2. Nao podera participar empresa em processo de falencia."""

_PAGE_2 = """3. DA HABILITACAO

3.1. Para fins de habilitacao, o licitante devera apresentar os seguintes documentos:
a) prova de regularidade fiscal;
b) prova de regularidade trabalhista;
c) atestado de capacidade tecnica.

4. DAS SANCOES

4.1. Pela inexecucao total ou parcial do contrato, a Administracao podera aplicar multa \
de ate 10% do valor do contrato."""


def test_chunk_document_segments_known_sections_with_correct_pages() -> None:
    chunks = chunk_document([_PAGE_1, _PAGE_2])
    sections = [c.section for c in chunks]

    assert "1. DO OBJETO" in sections
    assert "2. DAS CONDICOES DE PARTICIPACAO" in sections
    assert "3. DA HABILITACAO" in sections
    assert "4. DAS SANCOES" in sections

    objeto_chunk = next(c for c in chunks if c.section == "1. DO OBJETO")
    assert objeto_chunk.page_start == 1
    assert objeto_chunk.page_end == 1
    assert "aquisicao de materiais de escritorio" in objeto_chunk.content

    habilitacao_chunk = next(c for c in chunks if c.section == "3. DA HABILITACAO")
    assert habilitacao_chunk.page_start == 2
    assert habilitacao_chunk.page_end == 2


def test_chunk_document_does_not_treat_clause_text_as_a_new_heading() -> None:
    """Regressao: uma clausula que menciona uma palavra do vocabulario de secoes (ex.:
    "regularidade fiscal") no meio de uma frase NAO pode virar um cabecalho novo — so o
    vocabulario sozinho, sem parecer um titulo (maioria maiuscula), nao basta."""
    chunks = chunk_document([_PAGE_2])
    sections = {c.section for c in chunks}

    assert "a) prova de regularidade fiscal;" not in sections
    assert (
        "3.1. Para fins de habilitacao, o licitante devera apresentar os seguintes documentos:"
        not in sections
    )

    habilitacao_chunk = next(c for c in chunks if c.section == "3. DA HABILITACAO")
    assert "prova de regularidade fiscal" in habilitacao_chunk.content
    assert "prova de regularidade trabalhista" in habilitacao_chunk.content


def test_chunk_document_falls_back_to_single_section_without_headings() -> None:
    unstructured = "Este e um documento sem nenhuma secao reconhecivel. " * 30
    chunks = chunk_document([unstructured])

    assert len(chunks) >= 1
    assert all(c.section is None for c in chunks)
    assert all(c.chunk_type == ChunkType.PREAMBLE for c in chunks)


def test_chunk_document_returns_empty_list_for_blank_pages() -> None:
    assert chunk_document(["", "   \n  "]) == []
    assert chunk_document([]) == []


def test_chunk_document_hard_splits_oversized_paragraph() -> None:
    huge_paragraph = "palavra " * 1000  # bem maior que o teto de 1200 caracteres
    chunks = chunk_document([huge_paragraph])

    assert len(chunks) > 1
    assert all(len(c.content) <= 1200 for c in chunks)


def test_chunk_document_assigns_sequential_chunk_index() -> None:
    chunks = chunk_document([_PAGE_1, _PAGE_2])
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
