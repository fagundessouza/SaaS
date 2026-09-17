"""Dedup/versionamento de Tender contra Postgres real, e download/storage de documentos contra
MinIO real (ver domains/procurement/tenders/service.py).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from core.db.session import system_session
from domains.procurement.tenders.models import Tender, TenderDocument, TenderVersion
from domains.procurement.tenders.service import (
    IngestOutcome,
    ingest_raw_tender,
    store_tender_documents,
)
from ingestion.connectors.base import RawTender, RawTenderDocument, RawTenderItem
from tests.pdf_fixtures import make_native_text_pdf


def _raw_tender(external_id: str, objeto: str = "Objeto original") -> RawTender:
    return RawTender(
        source="pncp",
        external_id=external_id,
        orgao_cnpj="00394460000141",
        orgao_nome="Prefeitura Exemplo",
        unidade_nome="Secretaria de Administracao",
        modalidade="Pregao Eletronico",
        objeto=objeto,
        valor_estimado=Decimal("150000.50"),
        data_publicacao=date(2026, 9, 10),
        data_abertura_proposta=None,
        data_encerramento_proposta=None,
        situacao="Divulgada no PNCP",
        ano_compra=2026,
        sequencial_compra=1,
        raw_payload={"numeroControlePNCP": external_id, "objetoCompra": objeto},
        documents=[],
    )


async def test_ingest_new_tender_creates_tender_and_first_version() -> None:
    external_id = f"test-{uuid.uuid4()}"
    result = await ingest_raw_tender(_raw_tender(external_id))

    assert result.outcome == IngestOutcome.CREATED

    async with system_session() as session:
        tender = await session.get(Tender, result.tender_id)
        assert tender is not None
        assert tender.external_id == external_id
        assert tender.latest_version_number == 1

        versions = (
            (
                await session.execute(
                    select(TenderVersion).where(TenderVersion.tender_id == result.tender_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(versions) == 1
        assert versions[0].version_number == 1


async def test_ingest_same_payload_twice_is_unchanged() -> None:
    external_id = f"test-{uuid.uuid4()}"
    raw = _raw_tender(external_id)

    first = await ingest_raw_tender(raw)
    second = await ingest_raw_tender(raw)

    assert first.outcome == IngestOutcome.CREATED
    assert second.outcome == IngestOutcome.UNCHANGED
    assert first.tender_id == second.tender_id

    async with system_session() as session:
        versions = (
            (
                await session.execute(
                    select(TenderVersion).where(TenderVersion.tender_id == first.tender_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(versions) == 1  # nenhuma versao nova foi criada


async def test_ingest_changed_payload_creates_new_version() -> None:
    external_id = f"test-{uuid.uuid4()}"

    first = await ingest_raw_tender(_raw_tender(external_id, objeto="Objeto original"))
    second = await ingest_raw_tender(_raw_tender(external_id, objeto="Objeto retificado"))

    assert first.outcome == IngestOutcome.CREATED
    assert second.outcome == IngestOutcome.UPDATED
    assert first.tender_id == second.tender_id

    async with system_session() as session:
        tender = await session.get(Tender, first.tender_id)
        assert tender is not None
        assert tender.latest_version_number == 2
        assert tender.objeto == "Objeto retificado"

        versions = (
            (
                await session.execute(
                    select(TenderVersion)
                    .where(TenderVersion.tender_id == first.tender_id)
                    .order_by(TenderVersion.version_number)
                )
            )
            .scalars()
            .all()
        )
        assert [v.version_number for v in versions] == [1, 2]
        assert versions[0].raw_payload["objetoCompra"] == "Objeto original"
        assert versions[1].raw_payload["objetoCompra"] == "Objeto retificado"


class _FakeConnector:
    """Stub de Connector para testar store_tender_documents sem rede real."""

    source_name = "test"

    def __init__(self, content: bytes | None = None) -> None:
        self._content = (
            content
            if content is not None
            else make_native_text_pdf(
                "Edital de Pregao Eletronico numero 999/2026 - documento de teste"
            )
        )
        self.download_calls = 0

    def fetch_recent(self, data_inicial: date, data_final: date) -> AsyncIterator[RawTender]:
        raise NotImplementedError("nao usado nestes testes")

    async def fetch_documents(
        self, orgao_cnpj: str, ano_compra: int, sequencial_compra: int
    ) -> list[RawTenderDocument]:
        raise NotImplementedError("nao usado nestes testes")

    async def fetch_items(
        self, orgao_cnpj: str, ano_compra: int, sequencial_compra: int
    ) -> list[RawTenderItem]:
        raise NotImplementedError("nao usado nestes testes")

    async def download_document(self, download_url: str) -> bytes:
        self.download_calls += 1
        return self._content


async def test_store_tender_documents_downloads_and_persists() -> None:
    external_id = f"test-{uuid.uuid4()}"
    raw = _raw_tender(external_id)
    result = await ingest_raw_tender(raw)

    documents = [
        RawTenderDocument(
            external_document_id="1",
            title="Edital.pdf",
            download_url="https://pncp.gov.br/fake/edital.pdf",
            mime_type="application/pdf",
        )
    ]
    connector = _FakeConnector()

    await store_tender_documents(result.tender_id, "pncp", documents, connector)

    async with system_session() as session:
        docs = (
            (
                await session.execute(
                    select(TenderDocument).where(TenderDocument.tender_id == result.tender_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(docs) == 1
        assert docs[0].downloaded_at is not None
        assert docs[0].content_hash is not None
        assert docs[0].storage_key == f"global/tenders/{result.tender_id}/documents/1"
        assert docs[0].document_id is not None  # Document Intelligence (Fase 4) processou
        assert docs[0].processing_error is None

    # segunda chamada nao rebaixa um documento ja baixado
    await store_tender_documents(result.tender_id, "pncp", documents, connector)
    assert connector.download_calls == 1


async def test_store_tender_documents_records_failure_without_raising() -> None:
    external_id = f"test-{uuid.uuid4()}"
    raw = _raw_tender(external_id)
    result = await ingest_raw_tender(raw)

    documents = [
        RawTenderDocument(
            external_document_id="1",
            title="Edital.pdf",
            download_url="https://pncp.gov.br/fake/edital.pdf",
            mime_type="application/pdf",
        )
    ]

    class _FailingConnector:
        source_name = "test"

        def fetch_recent(self, data_inicial: date, data_final: date) -> AsyncIterator[RawTender]:
            raise NotImplementedError("nao usado nestes testes")

        async def fetch_documents(
            self, orgao_cnpj: str, ano_compra: int, sequencial_compra: int
        ) -> list[RawTenderDocument]:
            raise NotImplementedError("nao usado nestes testes")

        async def fetch_items(
            self, orgao_cnpj: str, ano_compra: int, sequencial_compra: int
        ) -> list[RawTenderItem]:
            raise NotImplementedError("nao usado nestes testes")

        async def download_document(self, download_url: str) -> bytes:
            raise ConnectionError("timeout simulado")

    await store_tender_documents(result.tender_id, "pncp", documents, _FailingConnector())

    async with system_session() as session:
        docs = (
            (
                await session.execute(
                    select(TenderDocument).where(TenderDocument.tender_id == result.tender_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(docs) == 1
        assert docs[0].downloaded_at is None
        assert docs[0].download_error == "timeout simulado"
