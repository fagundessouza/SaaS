"""Orquestracao do enriquecimento de CompanyProfile a partir do CNPJ."""

from __future__ import annotations

import uuid

from core.db.session import tenant_session
from core.events.publisher import publish_event
from domains.procurement.companies.cnpj_lookup import CnpjLookupError, lookup_cnpj
from domains.procurement.companies.models import CompanyProfile, EnrichmentStatus


def new_company_profile(
    *, tenant_id: uuid.UUID, legal_name: str, cnpj: str | None
) -> CompanyProfile:
    """Constroi (sem persistir) um CompanyProfile novo. O chamador decide quando/onde dar
    `session.add()` — normalmente dentro de uma transacao maior que tambem cria
    Tenant/User/Subscription (ver api/onboarding.py), por isso esta funcao nao abre sessao.
    """
    return CompanyProfile(tenant_id=tenant_id, legal_name=legal_name, cnpj=cnpj)


async def enrich_company_profile(tenant_id: uuid.UUID, company_profile_id: uuid.UUID) -> None:
    """Roda dentro do tenant_scope do chamador (ver domains/.../jobs.py). Nunca levanta —
    falha de enriquecimento e um estado de negocio normal (EnrichmentStatus.FAILED), nao uma
    excecao de job, para nao acionar retry indefinido do worker sobre uma fonte externa instavel.
    """
    async with tenant_session() as session:
        profile = await session.get(CompanyProfile, company_profile_id)
        if profile is None or profile.cnpj is None:
            return

        profile.enrichment_status = EnrichmentStatus.PENDING
        await session.flush()

    async with tenant_session() as session:
        profile = await session.get(CompanyProfile, company_profile_id)
        assert profile is not None

        try:
            result = await lookup_cnpj(profile.cnpj)  # type: ignore[arg-type]
        except CnpjLookupError as exc:
            profile.enrichment_status = EnrichmentStatus.FAILED
            profile.enrichment_error = str(exc)
            return

        profile.legal_name = result.legal_name or profile.legal_name
        profile.trade_name = result.trade_name
        profile.cnaes = result.cnaes
        profile.regions = [result.state] if result.state else []
        profile.raw_enrichment = result.raw
        profile.enrichment_status = EnrichmentStatus.ENRICHED
        profile.enrichment_error = None

        await publish_event(
            session,
            topic="CompanyProfileEnriched",
            payload={"company_profile_id": str(company_profile_id)},
            tenant_id=tenant_id,
        )
