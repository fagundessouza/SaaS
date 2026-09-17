"""Upsert de TenderItem contra Postgres real (ver domains/procurement/tenders/items_service.py).
Regra deterministica pura (ADR-0007) — sem IA, ao contrario de test_requirement_extraction.py.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from core.db.session import system_session
from domains.procurement.tenders.items_service import store_tender_items
from domains.procurement.tenders.models import TenderItem
from domains.procurement.tenders.service import ingest_raw_tender
from ingestion.connectors.base import RawTender, RawTenderItem


async def _create_tender() -> uuid.UUID:
    external_id = f"test-items-{uuid.uuid4()}"
    raw = RawTender(
        source="pncp",
        external_id=external_id,
        orgao_cnpj="00394460000141",
        orgao_nome="Prefeitura Exemplo",
        unidade_nome=None,
        uf="RN",
        municipio="Campo Grande",
        modalidade="Pregao Eletronico",
        objeto="Objeto de teste",
        valor_estimado=None,
        data_publicacao=date(2026, 9, 10),
        data_abertura_proposta=None,
        data_encerramento_proposta=None,
        situacao=None,
        ano_compra=2026,
        sequencial_compra=1,
        raw_payload={"numeroControlePNCP": external_id},
        documents=[],
    )
    result = await ingest_raw_tender(raw)
    return result.tender_id


def _raw_item(number: int, description: str = "Item de teste") -> RawTenderItem:
    return RawTenderItem(
        item_number=number,
        description=description,
        material_or_service="Material",
        quantity=Decimal("10"),
        unit_of_measure="Unidade",
        unit_estimated_value=Decimal("100.00"),
        total_estimated_value=Decimal("1000.00"),
    )


async def test_store_tender_items_creates_new_items() -> None:
    tender_id = await _create_tender()

    stored = await store_tender_items(tender_id, "pncp", [_raw_item(1), _raw_item(2)])

    assert stored == 2
    async with system_session() as session:
        items = (
            (await session.execute(select(TenderItem).where(TenderItem.tender_id == tender_id)))
            .scalars()
            .all()
        )
        assert {item.item_number for item in items} == {1, 2}


async def test_store_tender_items_is_idempotent_when_unchanged() -> None:
    tender_id = await _create_tender()
    raw_items = [_raw_item(1)]

    first = await store_tender_items(tender_id, "pncp", raw_items)
    second = await store_tender_items(tender_id, "pncp", raw_items)

    assert first == 1
    assert second == 0  # nada mudou, nao reconta como armazenado

    async with system_session() as session:
        items = (
            (await session.execute(select(TenderItem).where(TenderItem.tender_id == tender_id)))
            .scalars()
            .all()
        )
        assert len(items) == 1  # sem duplicata


async def test_store_tender_items_updates_changed_item_in_place() -> None:
    tender_id = await _create_tender()

    await store_tender_items(tender_id, "pncp", [_raw_item(1, description="Descricao original")])
    updated = await store_tender_items(
        tender_id, "pncp", [_raw_item(1, description="Descricao retificada")]
    )

    assert updated == 1
    async with system_session() as session:
        items = (
            (await session.execute(select(TenderItem).where(TenderItem.tender_id == tender_id)))
            .scalars()
            .all()
        )
        assert len(items) == 1  # atualizou a linha existente, nao duplicou
        assert items[0].description == "Descricao retificada"
