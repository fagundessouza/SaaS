"""Persistencia de TenderItem (Fase 6). Regra deterministica pura (ADR-0007): o PNCP ja entrega
item estruturado (ver ingestion/connectors/pncp.py `fetch_items`), entao aqui e so upsert por
`(tender_id, item_number)` — nenhuma IA envolvida, ao contrario da extracao de Requirement.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from core.db.session import system_session
from core.observability.logging import get_logger
from core.observability.metrics import tender_items_stored_total
from domains.procurement.tenders.models import TenderItem
from ingestion.connectors.base import RawTenderItem

logger = get_logger(__name__)


async def store_tender_items(tender_id: uuid.UUID, source: str, items: list[RawTenderItem]) -> int:
    """Upsert por `(tender_id, item_number)`: uma retificacao que muda a descricao/quantidade
    de um item existente atualiza a linha em vez de duplicar. Retorna quantos itens foram
    criados ou atualizados."""
    stored = 0
    async with system_session() as session:
        existing_by_number = {
            item.item_number: item
            for item in (
                await session.execute(select(TenderItem).where(TenderItem.tender_id == tender_id))
            )
            .scalars()
            .all()
        }

        for raw in items:
            existing = existing_by_number.get(raw.item_number)
            if existing is None:
                session.add(
                    TenderItem(
                        tender_id=tender_id,
                        item_number=raw.item_number,
                        description=raw.description,
                        material_or_service=raw.material_or_service,
                        quantity=raw.quantity,
                        unit_of_measure=raw.unit_of_measure,
                        unit_estimated_value=raw.unit_estimated_value,
                        total_estimated_value=raw.total_estimated_value,
                    )
                )
                stored += 1
                continue

            if (
                existing.description != raw.description
                or existing.material_or_service != raw.material_or_service
                or existing.quantity != raw.quantity
                or existing.unit_of_measure != raw.unit_of_measure
                or existing.unit_estimated_value != raw.unit_estimated_value
                or existing.total_estimated_value != raw.total_estimated_value
            ):
                existing.description = raw.description
                existing.material_or_service = raw.material_or_service
                existing.quantity = raw.quantity
                existing.unit_of_measure = raw.unit_of_measure
                existing.unit_estimated_value = raw.unit_estimated_value
                existing.total_estimated_value = raw.total_estimated_value
                stored += 1

    if stored:
        tender_items_stored_total.labels(source=source).inc(stored)
        logger.info("tender_items.stored", tender_id=str(tender_id), count=stored)
    return stored
