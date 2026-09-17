"""Interface de conector de ingestao (ver docs/SYSTEM_ARCHITECTURE.md e ADR-0009).

Um Connector so sabe buscar e normalizar dados da fonte externa em `RawTender` — nunca toca
banco, nunca conhece SQLAlchemy. Decidir se um RawTender vira uma nova Tender/TenderVersion e
responsabilidade de domains/procurement/tenders/service.py, nao do conector.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class RawTenderDocument:
    external_document_id: str
    title: str
    download_url: str
    mime_type: str | None


@dataclass(frozen=True)
class RawTender:
    source: str
    external_id: str
    orgao_cnpj: str
    orgao_nome: str
    unidade_nome: str | None
    modalidade: str
    objeto: str
    valor_estimado: Decimal | None
    data_publicacao: date | None
    data_abertura_proposta: datetime | None
    data_encerramento_proposta: datetime | None
    situacao: str | None
    # ano_compra + sequencial_compra identificam a compra para a API de documentos (ver
    # PncpConnector.fetch_documents). NUNCA usar um campo de "numero" em texto livre (ex.:
    # "PR08") para isso — so o par (ano, sequencial numerico) e estavel entre orgaos.
    ano_compra: int
    sequencial_compra: int
    raw_payload: dict[str, Any]
    documents: list[RawTenderDocument]


class Connector(Protocol):
    source_name: str

    def fetch_recent(self, data_inicial: date, data_final: date) -> AsyncIterator[RawTender]: ...

    async def fetch_documents(
        self, orgao_cnpj: str, ano_compra: int, sequencial_compra: int
    ) -> list[RawTenderDocument]: ...

    async def download_document(self, download_url: str) -> bytes: ...
