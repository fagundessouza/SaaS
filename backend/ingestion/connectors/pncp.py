"""Conector do PNCP — fonte canonica de ingestao (ver docs/adr/0009-pncp-fonte-canonica.md).

NOTA DE VERIFICACAO (ver docs/phase-reports/FASE_3_REPORT.md para o historico completo): a API
publica do PNCP esteve intermitente durante o desenvolvimento desta fase (HTTP 500 "Erro na
comunicacao com o banco de dados", timeouts, e um 422 de validacao de data, todos do lado do
servidor deles). Depois de varias tentativas, uma janela de disponibilidade permitiu verificar
ao vivo:
- `GET /contratacoes/publicacao` (listagem paginada) — campos confirmados exatamente como
  usados em `_parse_tender` (`numeroControlePNCP`, `orgaoEntidade.cnpj/razaoSocial`,
  `unidadeOrgao.nomeUnidade`, `modalidadeNome`, `objetoCompra`, `valorTotalEstimado`,
  `dataPublicacaoPncp`, `dataAberturaProposta`, `dataEncerramentoProposta`,
  `situacaoCompraNome`, `totalPaginas`). NAO ha campo `arquivos` inline nesta listagem.
- `GET /orgaos/{cnpj}/compras/{ano}/{sequencial}` (detalhe de uma compra) — path confirmado
  funcionando com `anoCompra`/`sequencialCompra` reais.
- **Pendente**: o sub-recurso de listagem de documentos (`fetch_documents` abaixo tenta
  `/arquivos`) retornou 404 nas duas compras testadas — pode ser o nome de path errado, ou as
  duas compras testadas simplesmente nao tinham documentos anexados (nao da para distinguir sem
  testar contra uma compra sabidamente com anexos). Tratar `fetch_documents` como best-effort ate
  isso ser confirmado — por isso ele nunca lanca excecao para o chamador, so loga e retorna lista
  vazia (ver corpo do metodo).

A instabilidade observada e a razao concreta (nao hipotetica) para o retry com backoff
implementado em `_request_with_retry`.

NOTA DE VERIFICACAO (Fase 6, `fetch_items`): o sub-recurso de itens NAO vive sob
`/api/consulta/v1` (`PNCP_BASE_URL`) como `/arquivos` — `/api/consulta/v1/orgaos/{cnpj}/compras/
{ano}/{sequencial}/itens` responde 404. O path confirmado ao vivo (compra real
`08084014000142/2024/57`, Municipio de Campo Grande/RN, 5 itens retornados com campos
`numeroItem`, `descricao`, `materialOuServicoNome`, `quantidade`, `unidadeMedida`,
`valorUnitarioEstimado`, `valorTotal`) e sob uma base diferente:
`https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens`
(`PNCP_ITEMS_BASE_URL` abaixo). Documentado explicitamente porque a inconsistencia de base URL
entre sub-recursos do mesmo `numeroControlePNCP` nao esta descrita no Manual de Integracao —
achada por tentativa direta contra a API real, nao por documentacao.

BUG REAL CORRIGIDO (achado ao comparar duas implementacoes independentes desta mesma fase, ver
docs/phase-reports/FASE_6_REPORT.md): a nota acima ja registrava que `/arquivos` sofre da MESMA
inconsistencia de base URL que `/itens`, mas so `fetch_items` tinha sido corrigido para usar
`PNCP_ITEMS_BASE_URL` — `fetch_documents` continuava chamando `_request_with_retry` sem
`base_url`, que por padrao usa `PNCP_BASE_URL` (a base errada para este sub-recurso). Confirmado
ao vivo contra a mesma compra real (`13183513000127/2025/173`): a base errada retorna 404 (os
"pendente" documentados acima), a base correta retorna 200 com a lista de documentos.
`fetch_documents` nunca baixou um documento real de producao ate esta correcao — o best-effort
silencioso (um 404 e tratado como "sem documentos") mascarou isso sem nenhum log de erro.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from core.observability.logging import get_logger
from core.observability.metrics import ingestion_errors_total, ingestion_items_fetched_total
from ingestion.connectors.base import RawTender, RawTenderDocument, RawTenderItem

logger = get_logger(__name__)

PNCP_BASE_URL = "https://pncp.gov.br/api/consulta/v1"
# Base diferente do resto do conector — ver nota de verificacao no topo do modulo.
PNCP_ITEMS_BASE_URL = "https://pncp.gov.br/api/pncp/v1"

# Codigos de modalidade de contratacao do PNCP (Manual de Integracao) — a API exige exatamente
# um codigo por requisicao, entao o conector itera sobre esta lista. Cobre as modalidades que
# mais geram volume de oportunidades para fornecedores; outras podem ser adicionadas sob demanda
# (ver ADR-0009 sobre nao cobrir especulativamente).
DEFAULT_MODALIDADES = (6, 4, 8)  # Pregao Eletronico, Concorrencia Eletronica, Dispensa

_PAGE_SIZE = 50
_MAX_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (2.0, 5.0, 10.0)


class PncpConnectorError(Exception):
    """Falha ao consultar/parsear o PNCP apos esgotar as tentativas de retry."""


class PncpConnector:
    source_name = "pncp"

    def __init__(
        self,
        base_url: str = PNCP_BASE_URL,
        timeout: float = 30.0,
        items_base_url: str = PNCP_ITEMS_BASE_URL,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._items_base_url = items_base_url

    async def fetch_recent(
        self,
        data_inicial: date,
        data_final: date,
        modalidades: tuple[int, ...] = DEFAULT_MODALIDADES,
    ) -> AsyncIterator[RawTender]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for modalidade in modalidades:
                async for raw_tender in self._fetch_modalidade(
                    client, data_inicial, data_final, modalidade
                ):
                    yield raw_tender

    async def _fetch_modalidade(
        self, client: httpx.AsyncClient, data_inicial: date, data_final: date, modalidade: int
    ) -> AsyncIterator[RawTender]:
        pagina = 1
        while True:
            params = {
                "dataInicial": data_inicial.strftime("%Y%m%d"),
                "dataFinal": data_final.strftime("%Y%m%d"),
                "codigoModalidadeContratacao": modalidade,
                "pagina": pagina,
                "tamanhoPagina": _PAGE_SIZE,
            }
            try:
                body = await self._request_with_retry(client, "/contratacoes/publicacao", params)
            except PncpConnectorError:
                ingestion_errors_total.labels(source=self.source_name).inc()
                logger.error("pncp.fetch_failed", modalidade=modalidade, pagina=pagina)
                return

            items = body.get("data", [])
            for item in items:
                try:
                    yield _parse_tender(item)
                    ingestion_items_fetched_total.labels(source=self.source_name).inc()
                except (KeyError, ValueError, InvalidOperation) as exc:
                    ingestion_errors_total.labels(source=self.source_name).inc()
                    logger.error(
                        "pncp.parse_failed",
                        error=str(exc),
                        numero_controle=item.get("numeroControlePNCP"),
                    )

            total_paginas = body.get("totalPaginas", 1)
            if pagina >= total_paginas or not items:
                return
            pagina += 1

    async def fetch_documents(
        self, orgao_cnpj: str, ano_compra: int, sequencial_compra: int
    ) -> list[RawTenderDocument]:
        """Busca os anexos de uma compra especifica. Chamado sob demanda (so para Tender novo
        ou com versao alterada, ver domains/procurement/tenders/service.py) — nao durante a
        listagem, que ja e uma chamada por pagina; buscar anexos de toda compra listada
        multiplicaria as chamadas a uma API que ja se mostrou instavel neste ambiente.

        BUG REAL CORRIGIDO: esta funcao chamava `_request_with_retry` sem `base_url`, que por
        padrao usa `self._base_url` (`/api/consulta/v1`, a mesma da listagem principal) — mas
        `/arquivos`, assim como `/itens` (ver `fetch_items`), vive sob `self._items_base_url`
        (`/api/pncp/v1`). Confirmado ao vivo contra uma compra real
        (`13183513000127/2025/173`): a base errada retorna 404 (os mesmos 404 que a nota
        original deste modulo documentava como "path nao confirmado"), a base correta retorna
        200 com a lista de documentos. Ou seja: `fetch_documents` nunca baixou um documento real
        de producao ate esta correcao — o "best-effort silencioso" abaixo (um 404 e tratado como
        "sem documentos") mascarou isso sem nenhum log de erro.
        """
        path = f"/orgaos/{orgao_cnpj}/compras/{ano_compra}/{sequencial_compra}/arquivos"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                body = await self._request_with_retry(
                    client, path, params={}, base_url=self._items_base_url
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return []
                ingestion_errors_total.labels(source=self.source_name).inc()
                logger.error(
                    "pncp.fetch_documents_failed",
                    orgao_cnpj=orgao_cnpj,
                    ano_compra=ano_compra,
                    sequencial_compra=sequencial_compra,
                    status_code=exc.response.status_code,
                )
                return []
            except PncpConnectorError:
                ingestion_errors_total.labels(source=self.source_name).inc()
                logger.error(
                    "pncp.fetch_documents_failed",
                    orgao_cnpj=orgao_cnpj,
                    ano_compra=ano_compra,
                    sequencial_compra=sequencial_compra,
                )
                return []

        items = body if isinstance(body, list) else body.get("data", [])
        return [
            RawTenderDocument(
                external_document_id=str(doc.get("sequencialDocumento", "")),
                title=doc.get("titulo", "documento"),
                download_url=doc.get("uri") or doc.get("url", ""),
                mime_type=None,
            )
            for doc in items
        ]

    async def fetch_items(
        self, orgao_cnpj: str, ano_compra: int, sequencial_compra: int
    ) -> list[RawTenderItem]:
        """Busca os itens/lotes de uma compra especifica, sob demanda (mesmo padrao de
        `fetch_documents`: so para Tender novo ou com versao alterada). Path e base URL
        confirmados ao vivo (ver nota no topo do modulo) — DIFERENTE da base usada pelo resto
        do conector.

        Um 404 aqui e tratado como "sem itens" (retorno vazio, sem erro) pela mesma razao ja
        documentada em `fetch_documents`: nao da para distinguir com certeza "path errado" de
        "compra sem itens cadastrados", e bloquear a ingestao por causa disso seria pior que
        simplesmente nao ter itens desta vez.
        """
        path = f"/orgaos/{orgao_cnpj}/compras/{ano_compra}/{sequencial_compra}/itens"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await self._request_raw_with_retry(
                    client, f"{self._items_base_url}{path}", params={}
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return []
                ingestion_errors_total.labels(source=self.source_name).inc()
                logger.error(
                    "pncp.fetch_items_failed",
                    orgao_cnpj=orgao_cnpj,
                    ano_compra=ano_compra,
                    sequencial_compra=sequencial_compra,
                    status_code=exc.response.status_code,
                )
                return []
            except PncpConnectorError:
                ingestion_errors_total.labels(source=self.source_name).inc()
                logger.error(
                    "pncp.fetch_items_failed",
                    orgao_cnpj=orgao_cnpj,
                    ano_compra=ano_compra,
                    sequencial_compra=sequencial_compra,
                )
                return []

        items = response.json()
        parsed: list[RawTenderItem] = []
        for item in items:
            try:
                parsed.append(_parse_item(item))
            except (KeyError, ValueError, InvalidOperation) as exc:
                ingestion_errors_total.labels(source=self.source_name).inc()
                logger.error(
                    "pncp.parse_item_failed",
                    error=str(exc),
                    orgao_cnpj=orgao_cnpj,
                    ano_compra=ano_compra,
                    sequencial_compra=sequencial_compra,
                )
        return parsed

    async def download_document(self, download_url: str) -> bytes:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await self._request_raw_with_retry(client, download_url)
            return response.content

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, Any],
        *,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        response = await self._request_raw_with_retry(
            client, f"{base_url or self._base_url}{path}", params=params
        )
        result: dict[str, Any] = response.json()
        return result

    async def _request_raw_with_retry(
        self, client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        """So tenta de novo erro 5xx/transporte (transiente, confirmado neste ambiente durante
        o desenvolvimento — ver nota no topo do modulo). Um 4xx (ex.: 404) e definitivo — nao
        adianta repetir a mesma requisicao 3 vezes — e propaga `httpx.HTTPStatusError`
        imediatamente para o chamador poder distinguir o caso (ex.: `fetch_documents` trata 404
        como "sem documentos", nao como falha de conector).
        """
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRY_ATTEMPTS):
            try:
                response = await client.get(url, params=params)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if response.status_code < 400:
                    return response
                if response.status_code < 500:
                    response.raise_for_status()  # 4xx: propaga sem retry
                last_error = httpx.HTTPStatusError(
                    f"PNCP retornou {response.status_code}",
                    request=response.request,
                    response=response,
                )

            logger.warning(
                "pncp.request_retry", attempt=attempt + 1, url=url, error=str(last_error)
            )
            if attempt < _MAX_RETRY_ATTEMPTS - 1:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt])

        raise PncpConnectorError(
            f"Falha ao consultar {url} apos {_MAX_RETRY_ATTEMPTS} tentativas"
        ) from last_error


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value).date()


def _to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _parse_item(item: dict[str, Any]) -> RawTenderItem:
    return RawTenderItem(
        item_number=int(item["numeroItem"]),
        description=item.get("descricao", ""),
        material_or_service=item.get("materialOuServicoNome"),
        quantity=_to_decimal(item.get("quantidade")),
        unit_of_measure=item.get("unidadeMedida"),
        # `orcamentoSigiloso=True` faz o PNCP omitir/zerar valores estimados de proposito (sigilo
        # de orcamento previsto em lei) — None aqui, nao 0, para nao confundir "sigiloso" com
        # "gratuito" a jusante.
        unit_estimated_value=(
            None
            if item.get("orcamentoSigiloso")
            else _to_decimal(item.get("valorUnitarioEstimado"))
        ),
        total_estimated_value=(
            None if item.get("orcamentoSigiloso") else _to_decimal(item.get("valorTotal"))
        ),
    )


def _parse_tender(item: dict[str, Any]) -> RawTender:
    orgao = item.get("orgaoEntidade") or {}
    unidade = item.get("unidadeOrgao") or {}

    external_id = item["numeroControlePNCP"]
    documents = [
        RawTenderDocument(
            external_document_id=str(doc.get("sequencialDocumento", "")),
            title=doc.get("titulo", "documento"),
            download_url=doc.get("uri") or doc.get("url", ""),
            mime_type=None,
        )
        for doc in item.get("arquivos") or []
    ]

    return RawTender(
        source="pncp",
        external_id=external_id,
        orgao_cnpj=orgao.get("cnpj", ""),
        orgao_nome=orgao.get("razaoSocial", ""),
        unidade_nome=unidade.get("nomeUnidade"),
        uf=unidade.get("ufSigla"),
        municipio=unidade.get("municipioNome"),
        modalidade=item.get("modalidadeNome", ""),
        objeto=item.get("objetoCompra", ""),
        valor_estimado=_to_decimal(item.get("valorTotalEstimado")),
        data_publicacao=_to_date(item.get("dataPublicacaoPncp")),
        data_abertura_proposta=_to_datetime(item.get("dataAberturaProposta")),
        data_encerramento_proposta=_to_datetime(item.get("dataEncerramentoProposta")),
        situacao=item.get("situacaoCompraNome"),
        ano_compra=int(item["anoCompra"]),
        sequencial_compra=int(item["sequencialCompra"]),
        raw_payload=item,
        documents=documents,
    )
