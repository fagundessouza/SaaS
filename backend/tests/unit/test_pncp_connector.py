"""Testes do conector PNCP contra respostas mockadas (ver nota de verificacao pendente em
ingestion/connectors/pncp.py — a API real esteve fora do ar durante o desenvolvimento desta
fase). O formato usado aqui segue o Manual de Integracao PNCP publicamente documentado.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

import ingestion.connectors.pncp as pncp_module
from ingestion.connectors.base import RawTender
from ingestion.connectors.pncp import PncpConnector, PncpConnectorError, _parse_tender

PNCP_BASE = "https://pncp.gov.br/api/consulta/v1"


@pytest.fixture(autouse=True)
def _no_backoff_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Testes de retry nao devem esperar o backoff real (ate 10s) — so o comportamento importa."""
    monkeypatch.setattr(pncp_module, "_RETRY_BACKOFF_SECONDS", (0.0, 0.0, 0.0))


def _sample_item(numero: str = "00394460000141-1-000001/2026") -> dict[str, Any]:
    return {
        "numeroControlePNCP": numero,
        "numeroCompra": "PR08",  # PNCP real: string livre, nao usar como identificador
        "sequencialCompra": 1,
        "anoCompra": 2026,
        "objetoCompra": "Aquisicao de material de escritorio",
        "modalidadeNome": "Pregao Eletronico",
        "situacaoCompraNome": "Divulgada no PNCP",
        "valorTotalEstimado": 150000.5,
        "dataPublicacaoPncp": "2026-09-10T14:00:00",
        "dataAberturaProposta": "2026-09-20T09:00:00",
        "dataEncerramentoProposta": "2026-09-25T09:00:00",
        "orgaoEntidade": {"cnpj": "00394460000141", "razaoSocial": "Prefeitura Exemplo"},
        "unidadeOrgao": {"nomeUnidade": "Secretaria de Administracao"},
    }


def test_parse_tender_maps_documented_fields() -> None:
    raw = _parse_tender(_sample_item())

    assert isinstance(raw, RawTender)
    assert raw.source == "pncp"
    assert raw.external_id == "00394460000141-1-000001/2026"
    assert raw.orgao_cnpj == "00394460000141"
    assert raw.orgao_nome == "Prefeitura Exemplo"
    assert raw.unidade_nome == "Secretaria de Administracao"
    assert raw.modalidade == "Pregao Eletronico"
    assert raw.objeto == "Aquisicao de material de escritorio"
    assert raw.valor_estimado == Decimal("150000.5")
    assert raw.data_publicacao == date(2026, 9, 10)
    assert raw.situacao == "Divulgada no PNCP"
    assert raw.ano_compra == 2026
    assert raw.sequencial_compra == 1
    assert raw.raw_payload["numeroControlePNCP"] == "00394460000141-1-000001/2026"


def test_parse_tender_handles_missing_optional_fields() -> None:
    item = _sample_item()
    del item["unidadeOrgao"]
    item["valorTotalEstimado"] = None

    raw = _parse_tender(item)

    assert raw.unidade_nome is None
    assert raw.valor_estimado is None


def test_parse_tender_requires_numero_controle() -> None:
    item = _sample_item()
    del item["numeroControlePNCP"]

    with pytest.raises(KeyError):
        _parse_tender(item)


@respx.mock
async def test_fetch_recent_paginates_across_modalidades() -> None:
    page1 = {
        "data": [_sample_item("A-1-000001/2026")],
        "totalPaginas": 2,
    }
    page2 = {
        "data": [_sample_item("A-1-000002/2026")],
        "totalPaginas": 2,
    }
    empty = {"data": [], "totalPaginas": 1}

    route = respx.get(f"{PNCP_BASE}/contratacoes/publicacao")
    route.side_effect = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=page2),
        httpx.Response(200, json=empty),
    ]

    connector = PncpConnector()
    results = [
        raw
        async for raw in connector.fetch_recent(
            date(2026, 9, 10), date(2026, 9, 16), modalidades=(6,)
        )
    ]

    assert [r.external_id for r in results] == ["A-1-000001/2026", "A-1-000002/2026"]


@respx.mock
async def test_fetch_recent_retries_on_5xx_then_succeeds() -> None:
    ok_page = {"data": [_sample_item()], "totalPaginas": 1}

    route = respx.get(f"{PNCP_BASE}/contratacoes/publicacao")
    route.side_effect = [
        httpx.Response(500, text="Erro na comunicacao com o banco de dados."),
        httpx.Response(200, json=ok_page),
    ]

    connector = PncpConnector()
    results = [
        raw
        async for raw in connector.fetch_recent(
            date(2026, 9, 10), date(2026, 9, 16), modalidades=(6,)
        )
    ]

    assert len(results) == 1
    assert route.call_count == 2


@respx.mock
async def test_fetch_recent_gives_up_after_max_retries_without_raising() -> None:
    """O conector nao propaga excecao para o chamador em falha persistente — registra erro e
    encerra o generator, para uma modalidade instavel nao derrubar o ciclo de ingestao inteiro
    (ver ingestion/pipeline/jobs.py, que roda uma modalidade por vez)."""
    respx.get(f"{PNCP_BASE}/contratacoes/publicacao").mock(
        return_value=httpx.Response(500, text="Erro na comunicacao com o banco de dados.")
    )

    connector = PncpConnector()
    results = [
        raw
        async for raw in connector.fetch_recent(
            date(2026, 9, 10), date(2026, 9, 16), modalidades=(6,)
        )
    ]

    assert results == []


async def test_request_with_retry_raises_connector_error_when_exhausted() -> None:
    connector = PncpConnector(base_url="https://pncp.invalido.exemplo/v1", timeout=1.0)

    with respx.mock:
        respx.get("https://pncp.invalido.exemplo/v1/contratacoes/publicacao").mock(
            return_value=httpx.Response(503)
        )
        async with httpx.AsyncClient(timeout=1.0) as client:
            with pytest.raises(PncpConnectorError):
                await connector._request_with_retry(client, "/contratacoes/publicacao", {})
