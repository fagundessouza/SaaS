"""Job completo de ingestao (ver ingestion/pipeline/jobs.py), com a API do PNCP mockada via
respx e persistencia real contra Postgres.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import respx
from sqlalchemy import select

from core.db.session import system_session
from domains.procurement.tenders.models import Tender
from ingestion.pipeline.jobs import run_pncp_ingestion_job

PNCP_BASE = "https://pncp.gov.br/api/consulta/v1"


def _mock_no_documents() -> None:
    """Toda Tender CREATED/UPDATED aciona fetch_documents (ver ingestion/pipeline/jobs.py) —
    sem isto, respx recusa a chamada nao mockada."""
    respx.get(url__regex=rf"{PNCP_BASE}/orgaos/.+/arquivos").mock(
        return_value=httpx.Response(404)
    )


def _item(numero: str) -> dict[str, Any]:
    return {
        "numeroControlePNCP": numero,
        "numeroCompra": "1",
        "sequencialCompra": 1,
        "anoCompra": 2026,
        "objetoCompra": "Objeto de teste do job de ingestao",
        "modalidadeNome": "Pregao Eletronico",
        "situacaoCompraNome": "Divulgada no PNCP",
        "valorTotalEstimado": 50000.0,
        "dataPublicacaoPncp": "2026-09-15T10:00:00",
        "orgaoEntidade": {"cnpj": "00394460000141", "razaoSocial": "Prefeitura Job Teste"},
        "unidadeOrgao": {"nomeUnidade": "Secretaria de Teste"},
    }


@respx.mock
async def test_run_pncp_ingestion_job_creates_tenders_and_returns_counts() -> None:
    numero_a = f"job-{uuid.uuid4()}"
    numero_b = f"job-{uuid.uuid4()}"

    page_with_data = {"data": [_item(numero_a), _item(numero_b)], "totalPaginas": 1}
    empty_page = {"data": [], "totalPaginas": 1}
    _mock_no_documents()

    route = respx.get(f"{PNCP_BASE}/contratacoes/publicacao")
    # 3 modalidades default (6, 4, 8): a primeira retorna 2 itens, as outras vazias.
    route.side_effect = [
        httpx.Response(200, json=page_with_data),
        httpx.Response(200, json=empty_page),
        httpx.Response(200, json=empty_page),
    ]

    counts = await run_pncp_ingestion_job({})

    assert counts["created"] == 2
    assert counts["unchanged"] == 0

    async with system_session() as session:
        result = await session.execute(
            select(Tender).where(Tender.external_id.in_([numero_a, numero_b]))
        )
        tenders = result.scalars().all()
        assert len(tenders) == 2
        assert {t.objeto for t in tenders} == {"Objeto de teste do job de ingestao"}


@respx.mock
async def test_run_pncp_ingestion_job_is_idempotent_on_rerun() -> None:
    numero = f"job-idem-{uuid.uuid4()}"
    page = {"data": [_item(numero)], "totalPaginas": 1}
    empty_page = {"data": [], "totalPaginas": 1}
    _mock_no_documents()

    route = respx.get(f"{PNCP_BASE}/contratacoes/publicacao")
    route.side_effect = [
        httpx.Response(200, json=page),
        httpx.Response(200, json=empty_page),
        httpx.Response(200, json=empty_page),
        httpx.Response(200, json=page),
        httpx.Response(200, json=empty_page),
        httpx.Response(200, json=empty_page),
    ]

    first_counts = await run_pncp_ingestion_job({})
    second_counts = await run_pncp_ingestion_job({})

    assert first_counts["created"] == 1
    assert second_counts["created"] == 0
    assert second_counts["unchanged"] == 1
