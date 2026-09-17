"""Job assincrono de ingestao do PNCP — roda periodicamente via cron do worker (ver
backend/worker.py). `ingestion` pode depender de `domains` (nao ha contrato proibindo isso em
pyproject.toml — apenas `core`/`ai_platform` nao podem importar `ingestion`), entao este modulo
e o unico lugar autorizado a combinar o Connector (so sabe buscar da fonte externa) com o
service de dominio (so sabe decidir dedup/versionamento e persistir).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from core.observability.logging import get_logger
from domains.procurement.tenders.service import (
    IngestOutcome,
    ingest_raw_tender,
    store_tender_documents,
)
from ingestion.connectors.pncp import PncpConnector

logger = get_logger(__name__)

# Janela de sobreposicao: reprocessar as ultimas N horas a cada ciclo, para nao perder itens
# publicados entre o fim de um ciclo e o inicio do proximo. `ingest_raw_tender` e idempotente
# por content_hash (ver service.py), entao reprocessar o mesmo item repetidamente e barato
# (vira UNCHANGED) — mais seguro do que arriscar um gap de cobertura.
_LOOKBACK_HOURS = 48


async def run_pncp_ingestion_job(ctx: dict[str, Any]) -> dict[str, int]:
    connector = PncpConnector()
    now = datetime.now(UTC)
    data_inicial = (now - timedelta(hours=_LOOKBACK_HOURS)).date()
    data_final = now.date()

    counts = {outcome.value: 0 for outcome in IngestOutcome}

    async for raw in connector.fetch_recent(data_inicial, data_final):
        result = await ingest_raw_tender(raw)
        counts[result.outcome.value] += 1

        if result.outcome in (IngestOutcome.CREATED, IngestOutcome.UPDATED):
            documents = await connector.fetch_documents(
                raw.orgao_cnpj, raw.ano_compra, raw.sequencial_compra
            )
            if documents:
                await store_tender_documents(result.tender_id, raw.source, documents, connector)

    logger.info("pncp_ingestion.completed", **counts)
    return counts
