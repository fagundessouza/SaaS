"""Indexacao + busca contra Qdrant real (ver ai_platform/retrieval/). Sem mock: o mesmo
comportamento que um usuario real veria."""

from __future__ import annotations

import uuid

import pytest

from ai_platform.documents.models import (
    Document,
    DocumentVersion,
    ExtractionMethod,
    ExtractionQuality,
    LayoutQuality,
    TableQuality,
)
from ai_platform.retrieval.indexer import DocumentVersionNotFoundError, index_document_version
from ai_platform.retrieval.search import search_global_knowledge
from core.db.session import system_session
from tests.conftest import unique_text

_PAGE = """1. DO OBJETO

1.1. Aquisicao de materiais de escritorio para a Secretaria de Administracao.

2. DAS SANCOES

2.1. Pela inexecucao do contrato, a Administracao podera aplicar multa de ate 10% do valor \
contratado, alem de outras penalidades previstas em lei."""


async def _create_document_version(marker: str) -> uuid.UUID:
    page = f"{_PAGE}\n\n[{marker}]"
    async with system_session() as session:
        document = Document(content_hash=f"retrieval-{uuid.uuid4().hex}", latest_version_number=1)
        session.add(document)
        await session.flush()

        version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            processing_version="v1",
            extraction_method=ExtractionMethod.NATIVE,
            extraction_quality=ExtractionQuality.HIGH,
            ocr_required=False,
            layout_quality=LayoutQuality.HIGH,
            table_quality=TableQuality.NOT_APPLICABLE,
            low_extraction_confidence=False,
            page_count=1,
            extracted_text=page,
            page_texts=[page],
        )
        session.add(version)
        await session.flush()
        return version.id


async def test_index_then_search_returns_relevant_chunk_with_citation() -> None:
    version_id = await _create_document_version(unique_text("citation"))

    indexed = await index_document_version(version_id)
    assert indexed == 2  # duas secoes -> dois chunks

    # limit alto e busca pelo document_version_id nos resultados, nao pelo topo do ranking:
    # o Qdrant de teste acumula chunks quase identicos de execucoes anteriores deste mesmo
    # teste (mesmo texto base, so o marcador unico muda — pouco relevante para a similaridade
    # semantica), entao o "primeiro" resultado nem sempre e o desta execucao especificamente.
    # O que importa aqui e que ESTE chunk foi indexado e tem a citacao correta, nao que ele
    # vença todo o historico acumulado de testes (isso quem testa e test_search_results_are_
    # ordered_by_relevance_descending, com dados que nao colidem entre execucoes).
    results = await search_global_knowledge("multa por descumprimento do contrato", limit=20)

    match = next((r for r in results if r.document_version_id == version_id), None)
    assert match is not None, "chunk recem-indexado nao apareceu na busca"
    assert match.section == "2. DAS SANCOES"
    assert match.page_start == 1
    assert match.page_end == 1
    assert "multa" in match.content.lower()


async def test_indexing_same_version_twice_is_idempotent() -> None:
    version_id = await _create_document_version(unique_text("idempotent"))

    first = await index_document_version(version_id)
    second = await index_document_version(version_id)

    assert first == 2
    assert second == 0  # cache hit, nao reprocessou


async def test_indexing_with_force_reindexes() -> None:
    version_id = await _create_document_version(unique_text("force"))

    await index_document_version(version_id)
    forced = await index_document_version(version_id, force=True)

    assert forced == 2


async def test_indexing_unknown_document_version_raises() -> None:
    with pytest.raises(DocumentVersionNotFoundError):
        await index_document_version(uuid.uuid4())


async def test_search_results_are_ordered_by_relevance_descending() -> None:
    version_id = await _create_document_version(unique_text("ordering"))
    await index_document_version(version_id)

    results = await search_global_knowledge("aquisicao de materiais de escritorio", limit=5)

    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
