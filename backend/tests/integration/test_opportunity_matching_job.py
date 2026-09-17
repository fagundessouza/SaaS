"""Job do Opportunity Engine de ponta a ponta contra Postgres real: tenant ativo + perfil
declarado + Tender recente -> Opportunity + OpportunityMatch + evento no outbox.

NOTA DE TESTE (4a vez que este padrao aparece no projeto — ver PROBLEMAS das Fases 2/3/4/5):
este job varre TODO tenant ativo contra TODO Tender recente, e o Postgres de teste nao e limpo
entre rodadas. Logo, o tenant criado aqui inevitavelmente tambem casa com tenders deixados por
outros testes (varios usam objeto "material de escritorio"), e o numero total de Opportunity do
tenant NAO e previsivel. Toda assercao aqui e feita sobre o tender especifico criado pelo
proprio teste, nunca sobre contagem absoluta de linhas do tenant.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from core.auth.service import create_tenant_with_owner
from core.db.session import system_session, tenant_session
from core.events.models import DomainEvent
from core.tenancy.context import tenant_scope
from core.tenancy.models import Tenant, TenantStatus
from domains.procurement.companies.models import CompanyProfile
from domains.procurement.companies.service import new_company_profile
from domains.procurement.opportunities.jobs import run_opportunity_matching_job
from domains.procurement.opportunities.models import Opportunity, OpportunityMatch
from domains.procurement.tenders.service import ingest_raw_tender
from ingestion.connectors.base import RawTender
from tests.conftest import unique_email


async def _create_tender(objeto: str, uf: str | None) -> uuid.UUID:
    external_id = f"opp-{uuid.uuid4()}"
    raw = RawTender(
        source="pncp",
        external_id=external_id,
        orgao_cnpj="00394460000141",
        orgao_nome="Prefeitura Exemplo",
        unidade_nome=None,
        uf=uf,
        municipio="Cidade Exemplo",
        modalidade="Pregao Eletronico",
        objeto=objeto,
        valor_estimado=None,
        data_publicacao=date(2026, 9, 17),
        data_abertura_proposta=None,
        data_encerramento_proposta=None,
        situacao=None,
        ano_compra=2026,
        sequencial_compra=1,
        raw_payload={"numeroControlePNCP": external_id, "objetoCompra": objeto},
        documents=[],
    )
    result = await ingest_raw_tender(raw)
    return result.tender_id


async def _create_tenant_with_profile(
    *,
    regions: list[str],
    products: list[str],
    status: TenantStatus = TenantStatus.ACTIVE,
) -> uuid.UUID:
    owner = await create_tenant_with_owner(
        company_name="Empresa Radar",
        email=unique_email("radar"),
        password="senha-forte-123",
    )
    with tenant_scope(owner.tenant_id):
        async with tenant_session() as session:
            profile = new_company_profile(
                tenant_id=owner.tenant_id, legal_name="Empresa Radar", cnpj=None
            )
            profile.regions = regions
            profile.products = products
            session.add(profile)

    if status is not TenantStatus.ACTIVE:
        async with system_session() as session:
            tenant = await session.get(Tenant, owner.tenant_id)
            assert tenant is not None
            tenant.status = status

    return owner.tenant_id


async def _opportunities_of(tenant_id: uuid.UUID) -> list[Opportunity]:
    with tenant_scope(tenant_id):
        async with tenant_session() as session:
            result = await session.execute(
                select(Opportunity).where(Opportunity.tenant_id == tenant_id)
            )
            return list(result.scalars().all())


async def test_job_creates_opportunity_with_decomposed_match_and_event() -> None:
    tender_id = await _create_tender("Aquisicao de material de escritorio diverso", "RN")
    tenant_id = await _create_tenant_with_profile(
        regions=["RN"], products=["material de escritorio"]
    )

    counts = await run_opportunity_matching_job({})

    assert counts["matched"] >= 1

    opportunities = await _opportunities_of(tenant_id)
    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.tender_id == tender_id
    assert opportunity.status.value == "discovered"

    with tenant_scope(tenant_id):
        async with tenant_session() as session:
            match = (
                await session.execute(
                    select(OpportunityMatch).where(
                        OpportunityMatch.opportunity_id == opportunity.id
                    )
                )
            ).scalar_one()
            # Decomposicao obrigatoria: criterio a criterio, sem score agregado.
            assert match.compatibility["region"]["matched"] is True
            assert match.compatibility["keyword"]["matched"] is True
            assert match.confidence == {"region": 1.0, "keyword": 1.0}

    async with system_session() as session:
        events = (
            (
                await session.execute(
                    select(DomainEvent).where(
                        DomainEvent.topic == "OpportunityMatched",
                        DomainEvent.tenant_id == tenant_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].payload["tender_id"] == str(tender_id)


async def test_job_is_idempotent_across_runs() -> None:
    await _create_tender("Aquisicao de material de escritorio para secretarias", "PB")
    tenant_id = await _create_tenant_with_profile(
        regions=["PB"], products=["material de escritorio"]
    )

    await run_opportunity_matching_job({})
    first = await _opportunities_of(tenant_id)
    await run_opportunity_matching_job({})
    second = await _opportunities_of(tenant_id)

    assert len(first) == len(second) == 1
    assert first[0].id == second[0].id  # nao recriou nem duplicou


async def test_job_skips_tender_from_other_region() -> None:
    await _create_tender("Aquisicao de material de escritorio para a prefeitura", "SP")
    tenant_id = await _create_tenant_with_profile(
        regions=["AC"], products=["material de escritorio"]
    )

    await run_opportunity_matching_job({})

    assert await _opportunities_of(tenant_id) == []


async def test_job_skips_tenant_without_company_profile() -> None:
    await _create_tender("Aquisicao de material de escritorio", "RN")
    owner = await create_tenant_with_owner(
        company_name="Sem Perfil", email=unique_email("sem-perfil"), password="senha-forte-123"
    )

    await run_opportunity_matching_job({})

    assert await _opportunities_of(owner.tenant_id) == []


async def test_job_skips_suspended_tenant() -> None:
    await _create_tender("Aquisicao de material de escritorio urgente", "RN")
    tenant_id = await _create_tenant_with_profile(
        regions=["RN"],
        products=["material de escritorio"],
        status=TenantStatus.SUSPENDED,
    )

    await run_opportunity_matching_job({})

    assert await _opportunities_of(tenant_id) == []


async def test_job_skips_profile_without_declared_products() -> None:
    await _create_tender("Aquisicao de material de escritorio comum", "RN")
    tenant_id = await _create_tenant_with_profile(regions=["RN"], products=[])

    await run_opportunity_matching_job({})

    assert await _opportunities_of(tenant_id) == []


async def test_profile_without_regions_matches_any_uf() -> None:
    await _create_tender("Aquisicao de material de escritorio para o almoxarifado", "AM")
    tenant_id = await _create_tenant_with_profile(regions=[], products=["material de escritorio"])

    await run_opportunity_matching_job({})

    opportunities = await _opportunities_of(tenant_id)
    assert len(opportunities) >= 1

    with tenant_scope(tenant_id):
        async with tenant_session() as session:
            profile = (
                await session.execute(
                    select(CompanyProfile).where(CompanyProfile.tenant_id == tenant_id)
                )
            ).scalar_one()
            assert profile.regions == []
