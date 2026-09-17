"""Extracao de Requirement a partir de chunks ja indexados (ver
domains/procurement/tenders/requirements_service.py) — Postgres + Qdrant reais, sem mock, mesmo
espirito de tests/integration/test_retrieval.py (Fase 5)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_platform.documents.models import (
    Document,
    DocumentVersion,
    ExtractionMethod,
    ExtractionQuality,
    LayoutQuality,
    TableQuality,
)
from ai_platform.retrieval.indexer import index_document_version
from core.db.session import system_session
from domains.procurement.tenders.models import Requirement, RequirementCategory, Tender
from domains.procurement.tenders.requirements_service import (
    extract_requirements_for_document_version,
)
from tests.conftest import unique_text

_PAGE = """1. DO OBJETO

1.1. Contratacao de empresa especializada para fornecimento de materiais de escritorio.

8. DA HABILITACAO

8.1. Para fins de habilitacao fiscal, a licitante devera apresentar certidao negativa de \
debitos federais, estaduais e municipais, prova de regularidade com o FGTS e certidao negativa \
de debitos trabalhistas (CNDT), sob pena de inabilitacao."""


async def _create_tender(session: AsyncSession) -> uuid.UUID:
    tender = Tender(
        source="pncp",
        external_id=f"test-requirement-{uuid.uuid4()}",
        orgao_cnpj="00394460000141",
        orgao_nome="Prefeitura Exemplo",
        unidade_nome=None,
        modalidade="Pregao Eletronico",
        objeto="Objeto de teste",
        valor_estimado=None,
        data_publicacao=None,
        data_abertura_proposta=None,
        data_encerramento_proposta=None,
        situacao=None,
        latest_version_number=1,
    )
    session.add(tender)
    await session.flush()
    return tender.id


async def _create_document_version(session: AsyncSession, page: str) -> uuid.UUID:
    document = Document(content_hash=f"requirement-{uuid.uuid4().hex}", latest_version_number=1)
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
    return version.id


async def _create_tender_and_document_version(marker: str) -> tuple[uuid.UUID, uuid.UUID]:
    page = f"{_PAGE}\n\n[{marker}]"
    async with system_session() as session:
        tender_id = await _create_tender(session)
        version_id = await _create_document_version(session, page)
        return tender_id, version_id


async def test_extract_requirements_classifies_habilitacao_clause_as_fiscal() -> None:
    tender_id, version_id = await _create_tender_and_document_version(unique_text("fiscal-clause"))
    await index_document_version(version_id)

    created = await extract_requirements_for_document_version(tender_id, version_id)

    assert created == 1  # so a secao "DA HABILITACAO" e candidata, "DO OBJETO" nao

    async with system_session() as session:
        requirements = (
            (
                await session.execute(
                    select(Requirement).where(Requirement.document_version_id == version_id)
                )
            )
            .scalars()
            .all()
        )

    assert len(requirements) == 1
    requirement = requirements[0]
    assert requirement.tender_id == tender_id
    assert requirement.category == RequirementCategory.FISCAL
    assert requirement.section == "8. DA HABILITACAO"
    assert requirement.page_start == 1
    assert requirement.page_end == 1
    assert "certidao negativa" in requirement.description.lower()
    assert 0.0 <= requirement.confidence <= 1.0


async def test_extract_requirements_is_idempotent() -> None:
    tender_id, version_id = await _create_tender_and_document_version(unique_text("idempotent"))
    await index_document_version(version_id)

    first = await extract_requirements_for_document_version(tender_id, version_id)
    second = await extract_requirements_for_document_version(tender_id, version_id)

    assert first == 1
    assert second == 0  # cache hit, nao reprocessou


async def test_extract_requirements_with_force_reextracts() -> None:
    tender_id, version_id = await _create_tender_and_document_version(unique_text("force"))
    await index_document_version(version_id)

    await extract_requirements_for_document_version(tender_id, version_id)
    forced = await extract_requirements_for_document_version(tender_id, version_id, force=True)

    assert forced == 1

    async with system_session() as session:
        requirements = (
            (
                await session.execute(
                    select(Requirement).where(Requirement.document_version_id == version_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(requirements) == 1  # forcar reextracao nao duplica


async def test_extract_requirements_returns_zero_when_no_habilitacao_section() -> None:
    marker = unique_text("no-habilitacao")
    page = f"1. DO OBJETO\n\n1.1. Contratacao de servico de limpeza predial.\n\n[{marker}]"

    async with system_session() as session:
        tender_id = await _create_tender(session)
        version_id = await _create_document_version(session, page)

    await index_document_version(version_id)

    created = await extract_requirements_for_document_version(tender_id, version_id)

    assert created == 0
