"""GET /v1/knowledge/search — qualquer usuario autenticado, sem escopo de tenant (conteudo
GLOBAL, ver api/v1/knowledge.py)."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest

from ai_platform.documents.models import (
    Document,
    DocumentVersion,
    ExtractionMethod,
    ExtractionQuality,
    LayoutQuality,
    TableQuality,
)
from ai_platform.retrieval.indexer import index_document_version
from api.main import app
from core.db.session import system_session
from tests.conftest import unique_email, unique_text


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_search_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/knowledge/search", params={"q": "objeto do edital"})
    assert response.status_code == 401


async def test_search_returns_indexed_chunk(client: httpx.AsyncClient) -> None:
    marker = unique_text("api-search")
    page = f"1. DO OBJETO\n\nAquisicao de equipamentos de informatica.\n\n[{marker}]"

    async with system_session() as session:
        document = Document(content_hash=f"api-search-{marker}", latest_version_number=1)
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
        version_id = version.id

    await index_document_version(version_id)

    signup = await client.post(
        "/v1/auth/signup",
        json={
            "company_name": "Empresa Busca",
            "email": unique_email("busca"),
            "password": "senha-forte-123",
        },
    )
    access_token = signup.json()["access_token"]

    response = await client.get(
        "/v1/knowledge/search",
        params={"q": "compra de computadores", "limit": 20},
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    results = response.json()
    # busca pelo document_version_id nos resultados, nao pelo topo do ranking — mesma razao de
    # tests/integration/test_retrieval.py: o Qdrant de teste acumula chunks quase identicos de
    # execucoes anteriores deste teste.
    match = next((r for r in results if r["document_version_id"] == str(version_id)), None)
    assert match is not None, "chunk recem-indexado nao apareceu na busca"
    assert match["section"] == "1. DO OBJETO"
