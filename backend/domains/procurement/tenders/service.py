"""Decide se um RawTender vira uma Tender nova, uma nova TenderVersion (retificacao), ou e
descartado por ja ter sido ingerido (mesmo content_hash) — e orquestra o download/storage dos
documentos anexos. Ver ingestion/pipeline/jobs.py para quem chama isto.
"""

from __future__ import annotations

import enum
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from ai_platform.documents.service import get_or_process_document
from core.db.session import system_session
from core.events.publisher import publish_event
from core.observability.logging import get_logger
from core.observability.metrics import (
    tender_documents_stored_total,
    tenders_created_total,
    tenders_updated_total,
)
from core.storage.client import get_storage_client
from domains.procurement.tenders.models import Tender, TenderDocument, TenderVersion
from ingestion.connectors.base import Connector, RawTender, RawTenderDocument

logger = get_logger(__name__)


class IngestOutcome(enum.StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class IngestResult:
    outcome: IngestOutcome
    tender_id: uuid.UUID


def compute_content_hash(raw_payload: dict[str, Any]) -> str:
    canonical = json.dumps(raw_payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def ingest_raw_tender(raw: RawTender) -> IngestResult:
    content_hash = compute_content_hash(raw.raw_payload)

    async with system_session() as session:
        result = await session.execute(
            select(Tender).where(Tender.source == raw.source, Tender.external_id == raw.external_id)
        )
        tender = result.scalar_one_or_none()

        if tender is None:
            tender = Tender(
                source=raw.source,
                external_id=raw.external_id,
                orgao_cnpj=raw.orgao_cnpj,
                orgao_nome=raw.orgao_nome,
                unidade_nome=raw.unidade_nome,
                modalidade=raw.modalidade,
                objeto=raw.objeto,
                valor_estimado=raw.valor_estimado,
                data_publicacao=raw.data_publicacao,
                data_abertura_proposta=raw.data_abertura_proposta,
                data_encerramento_proposta=raw.data_encerramento_proposta,
                situacao=raw.situacao,
                latest_version_number=1,
            )
            session.add(tender)
            await session.flush()

            session.add(
                TenderVersion(
                    tender_id=tender.id,
                    version_number=1,
                    content_hash=content_hash,
                    raw_payload=raw.raw_payload,
                )
            )
            await publish_event(
                session,
                topic="TenderCreated",
                payload={"tender_id": str(tender.id), "external_id": raw.external_id},
                tenant_id=None,
            )
            tenders_created_total.labels(source=raw.source).inc()
            logger.info("tender.created", external_id=raw.external_id, tender_id=str(tender.id))
            return IngestResult(outcome=IngestOutcome.CREATED, tender_id=tender.id)

        latest_version = await session.execute(
            select(TenderVersion)
            .where(TenderVersion.tender_id == tender.id)
            .order_by(TenderVersion.version_number.desc())
            .limit(1)
        )
        current = latest_version.scalar_one()

        if current.content_hash == content_hash:
            return IngestResult(outcome=IngestOutcome.UNCHANGED, tender_id=tender.id)

        new_version_number = tender.latest_version_number + 1
        session.add(
            TenderVersion(
                tender_id=tender.id,
                version_number=new_version_number,
                content_hash=content_hash,
                raw_payload=raw.raw_payload,
            )
        )
        tender.latest_version_number = new_version_number
        tender.objeto = raw.objeto
        tender.valor_estimado = raw.valor_estimado
        tender.data_abertura_proposta = raw.data_abertura_proposta
        tender.data_encerramento_proposta = raw.data_encerramento_proposta
        tender.situacao = raw.situacao

        await publish_event(
            session,
            topic="TenderUpdated",
            payload={
                "tender_id": str(tender.id),
                "external_id": raw.external_id,
                "version_number": new_version_number,
            },
            tenant_id=None,
        )
        tenders_updated_total.labels(source=raw.source).inc()
        logger.info(
            "tender.updated",
            external_id=raw.external_id,
            tender_id=str(tender.id),
            version=new_version_number,
        )
        return IngestResult(outcome=IngestOutcome.UPDATED, tender_id=tender.id)


async def store_tender_documents(
    tender_id: uuid.UUID,
    source: str,
    documents: list[RawTenderDocument],
    connector: Connector,
) -> None:
    """Baixa e armazena anexos ainda nao baixados. Chamado apenas para Tender CREATED/UPDATED
    (ver ingestion/pipeline/jobs.py) — nunca para UNCHANGED, para nao rebaixar documentos ja
    presentes a cada ciclo de ingestao.
    """
    storage = get_storage_client()

    for doc in documents:
        async with system_session() as session:
            result = await session.execute(
                select(TenderDocument).where(
                    TenderDocument.tender_id == tender_id,
                    TenderDocument.external_document_id == doc.external_document_id,
                )
            )
            existing = result.scalar_one_or_none()
            if existing is not None and existing.downloaded_at is not None:
                continue

            record = existing or TenderDocument(
                tender_id=tender_id,
                external_document_id=doc.external_document_id,
                title=doc.title,
                source_url=doc.download_url,
            )
            if existing is None:
                session.add(record)

            try:
                content = await connector.download_document(doc.download_url)
            except Exception as exc:  # noqa: BLE001 — falha de download nao pode derrubar o ciclo
                record.download_error = str(exc)
                tender_documents_stored_total.labels(source=source, status="failed").inc()
                logger.error(
                    "tender_document.download_failed",
                    tender_id=str(tender_id),
                    external_document_id=doc.external_document_id,
                    error=str(exc),
                )
                continue

            content_hash = hashlib.sha256(content).hexdigest()
            storage_key = storage.put_global_object(
                key=f"tenders/{tender_id}/documents/{doc.external_document_id}",
                body=content,
                content_type=doc.mime_type or "application/octet-stream",
            )
            record.content_hash = content_hash
            record.storage_key = storage_key
            record.downloaded_at = datetime.now(UTC)
            record.download_error = None
            await session.flush()
            record_id = record.id
            tender_documents_stored_total.labels(source=source, status="stored").inc()

        # Document Intelligence roda fora da transacao de download (pode ser lento — render de
        # pagina + OCR) e abre sua propria sessao internamente (get_or_process_document); nunca
        # deixa uma falha de processamento derrubar a ingestao do documento em si, que ja foi
        # salvo com sucesso acima.
        try:
            processing = await get_or_process_document(content)
        except Exception as exc:  # noqa: BLE001 — falha de processamento nao e falha de ingestao
            logger.error(
                "tender_document.processing_failed",
                tender_id=str(tender_id),
                external_document_id=doc.external_document_id,
                error=str(exc),
            )
            async with system_session() as session:
                doc_record = await session.get(TenderDocument, record_id)
                assert doc_record is not None
                doc_record.processing_error = str(exc)
            continue

        async with system_session() as session:
            doc_record = await session.get(TenderDocument, record_id)
            assert doc_record is not None
            doc_record.document_id = processing.document_id
            doc_record.processing_error = None
