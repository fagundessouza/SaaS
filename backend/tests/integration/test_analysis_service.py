"""generate_analysis contra Postgres + fastembed real (sem mock) — ver
domains/procurement/analysis/service.py. Mesmo padrao de teste de
tests/integration/test_requirement_extraction.py (Fase 6).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from ai_platform.documents.models import (
    Document,
    DocumentVersion,
    ExtractionMethod,
    ExtractionQuality,
    LayoutQuality,
    TableQuality,
)
from core.auth.service import create_tenant_with_owner
from core.db.session import system_session, tenant_session
from core.tenancy.context import tenant_scope
from domains.procurement.analysis.models import Analysis, EvidenceKind, FindingStatus
from domains.procurement.analysis.service import (
    AnalysisNotFoundError,
    CompanyProfileNotFoundError,
    OpportunityNotFoundError,
    generate_analysis,
    get_analysis_with_findings,
)
from domains.procurement.companies.models import Attestation, Certificate, CompanyProfile
from domains.procurement.opportunities.models import Opportunity
from domains.procurement.tenders.models import Requirement, RequirementCategory, Tender
from tests.conftest import unique_email, unique_text

_PAGE = "edital de teste — texto irrelevante, Requirement e inserido diretamente"


async def _create_tender_with_requirements(marker: str) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    async with system_session() as session:
        tender = Tender(
            source="pncp",
            external_id=f"analysis-test-{marker}",
            orgao_cnpj="00394460000141",
            orgao_nome="Orgao Teste",
            unidade_nome=None,
            uf="RN",
            municipio="Cidade Teste",
            modalidade="Pregao Eletronico",
            objeto="Objeto teste",
            valor_estimado=None,
            data_publicacao=None,
            data_abertura_proposta=None,
            data_encerramento_proposta=None,
            situacao=None,
            latest_version_number=1,
        )
        session.add(tender)
        await session.flush()
        tender_id = tender.id

        document = Document(content_hash=f"analysis-doc-{marker}", latest_version_number=1)
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
            extracted_text=_PAGE,
            page_texts=[_PAGE],
        )
        session.add(version)
        await session.flush()
        version_id = version.id

        requirement_ids: dict[str, uuid.UUID] = {}
        for key, category, description in [
            ("juridica", RequirementCategory.JURIDICA, "contrato social registrado"),
            ("fiscal", RequirementCategory.FISCAL, "certidao negativa de debitos federais"),
            (
                "tecnica",
                RequirementCategory.TECNICA,
                "atestado de capacidade tecnica em desenvolvimento de software",
            ),
        ]:
            requirement = Requirement(
                tender_id=tender_id,
                category=category,
                # Sem sufixo de marcador unico aqui de proposito: Requirement nao tem constraint
                # de unicidade sobre a descricao (so (document_version_id, chunk_index), ver
                # models.py), e o texto limpo evita diluir a similaridade semantica no teste de
                # embedding abaixo (mesmo cuidado documentado no Fase 5 sobre preambulo).
                description=description,
                confidence=1.0,
                document_version_id=version_id,
                chunk_index=len(requirement_ids),
                section=f"secao {key}",
                page_start=1,
                page_end=1,
            )
            session.add(requirement)
            await session.flush()
            requirement_ids[key] = requirement.id

        return tender_id, requirement_ids


async def _create_tenant_with_profile(prefix: str) -> uuid.UUID:
    owner = await create_tenant_with_owner(
        company_name=f"Empresa {prefix}", email=unique_email(prefix), password="senha-forte-123"
    )
    with tenant_scope(owner.tenant_id):
        async with tenant_session() as session:
            session.add(
                CompanyProfile(tenant_id=owner.tenant_id, legal_name=f"Empresa {prefix} LTDA")
            )
    return owner.tenant_id


async def _get_company_profile_id(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session() as session:
        result = await session.execute(
            select(CompanyProfile.id).where(CompanyProfile.tenant_id == tenant_id)
        )
        return result.scalar_one()


async def _create_opportunity(tenant_id: uuid.UUID, tender_id: uuid.UUID) -> uuid.UUID:
    with tenant_scope(tenant_id):
        async with tenant_session() as session:
            opportunity = Opportunity(tenant_id=tenant_id, tender_id=tender_id)
            session.add(opportunity)
            await session.flush()
            return opportunity.id


async def test_analysis_covers_missing_met_and_expired_certificates() -> None:
    marker = unique_text("analysis-cert")
    tenant_id = await _create_tenant_with_profile(f"cert-{marker[:8]}")
    tender_id, requirement_ids = await _create_tender_with_requirements(marker)

    with tenant_scope(tenant_id):
        company_profile_id = await _get_company_profile_id(tenant_id)
        async with tenant_session() as session:
            # FISCAL: certidao valida -> MET. JURIDICA: nenhuma certidao -> MISSING. Nenhum
            # atestado cadastrado -> TECNICA vira MISSING tambem.
            session.add(
                Certificate(
                    tenant_id=tenant_id,
                    company_profile_id=company_profile_id,
                    category=RequirementCategory.FISCAL,
                    name="CND Federal",
                    expires_at=date.today() + timedelta(days=30),
                )
            )

        opportunity_id = await _create_opportunity(tenant_id, tender_id)
        await generate_analysis(opportunity_id)
        analysis, findings = await get_analysis_with_findings(opportunity_id)

    assert isinstance(analysis, Analysis)
    by_requirement = {finding.requirement_id: (finding, evidence) for finding, evidence in findings}

    juridica_finding, juridica_evidence = by_requirement[requirement_ids["juridica"]]
    assert juridica_finding.status == FindingStatus.MISSING
    assert len(juridica_evidence) == 1
    assert juridica_evidence[0].kind == EvidenceKind.REQUIREMENT_TEXT

    fiscal_finding, fiscal_evidence = by_requirement[requirement_ids["fiscal"]]
    assert fiscal_finding.status == FindingStatus.MET
    evidence_kinds = {e.kind for e in fiscal_evidence}
    assert evidence_kinds == {EvidenceKind.REQUIREMENT_TEXT, EvidenceKind.CERTIFICATE_DATA}

    tecnica_finding, _ = by_requirement[requirement_ids["tecnica"]]
    assert tecnica_finding.status == FindingStatus.MISSING


async def test_analysis_marks_expired_certificate() -> None:
    marker = unique_text("analysis-expired")
    tenant_id = await _create_tenant_with_profile(f"exp-{marker[:8]}")
    tender_id, requirement_ids = await _create_tender_with_requirements(marker)

    with tenant_scope(tenant_id):
        company_profile_id = await _get_company_profile_id(tenant_id)
        async with tenant_session() as session:
            session.add(
                Certificate(
                    tenant_id=tenant_id,
                    company_profile_id=company_profile_id,
                    category=RequirementCategory.FISCAL,
                    name="CND Vencida",
                    expires_at=date.today() - timedelta(days=1),
                )
            )

        opportunity_id = await _create_opportunity(tenant_id, tender_id)
        await generate_analysis(opportunity_id)
        _, findings = await get_analysis_with_findings(opportunity_id)

    by_requirement = {finding.requirement_id: finding for finding, _ in findings}
    assert by_requirement[requirement_ids["fiscal"]].status == FindingStatus.EXPIRED


async def test_analysis_matches_attestation_by_semantic_similarity() -> None:
    marker = unique_text("analysis-attestation")
    tenant_id = await _create_tenant_with_profile(f"att-{marker[:8]}")
    tender_id, requirement_ids = await _create_tender_with_requirements(marker)

    with tenant_scope(tenant_id):
        company_profile_id = await _get_company_profile_id(tenant_id)
        async with tenant_session() as session:
            session.add(
                Attestation(
                    tenant_id=tenant_id,
                    company_profile_id=company_profile_id,
                    issuing_org="Secretaria de TI Exemplo",
                    object_description="Desenvolvimento de sistema de software sob medida",
                )
            )

        opportunity_id = await _create_opportunity(tenant_id, tender_id)
        await generate_analysis(opportunity_id)
        _, findings = await get_analysis_with_findings(opportunity_id)

    by_requirement = {finding.requirement_id: (finding, evidence) for finding, evidence in findings}
    tecnica_finding, tecnica_evidence = by_requirement[requirement_ids["tecnica"]]
    assert tecnica_finding.status in (FindingStatus.MET, FindingStatus.NEEDS_REVIEW)
    assert any(e.kind == EvidenceKind.ATTESTATION_DATA for e in tecnica_evidence)


async def test_generate_analysis_is_regenerable_without_duplicating_findings() -> None:
    marker = unique_text("analysis-regenerate")
    tenant_id = await _create_tenant_with_profile(f"regen-{marker[:8]}")
    tender_id, _ = await _create_tender_with_requirements(marker)

    with tenant_scope(tenant_id):
        opportunity_id = await _create_opportunity(tenant_id, tender_id)
        first_id = await generate_analysis(opportunity_id)
        second_id = await generate_analysis(opportunity_id)

        assert first_id != second_id  # substituida, nao versionada (ver docstring do modulo)

        analysis, findings = await get_analysis_with_findings(opportunity_id)
        assert analysis.id == second_id
        assert len(findings) == 3  # nao duplicou os 3 Requirement em 6


async def test_generate_analysis_raises_for_unknown_opportunity() -> None:
    marker = unique_text("analysis-unknown-opp")
    tenant_id = await _create_tenant_with_profile(f"unknown-{marker[:8]}")

    with tenant_scope(tenant_id), pytest.raises(OpportunityNotFoundError):
        await generate_analysis(uuid.uuid4())


async def test_generate_analysis_raises_when_company_profile_missing() -> None:
    marker = unique_text("analysis-no-profile")
    owner = await create_tenant_with_owner(
        company_name="Sem Perfil", email=unique_email(f"noprofile-{marker[:8]}"),
        password="senha-forte-123",
    )
    tender_id, _ = await _create_tender_with_requirements(marker)

    with tenant_scope(owner.tenant_id):
        opportunity_id = await _create_opportunity(owner.tenant_id, tender_id)
        with pytest.raises(CompanyProfileNotFoundError):
            await generate_analysis(opportunity_id)


async def test_get_analysis_raises_when_none_generated_yet() -> None:
    marker = unique_text("analysis-not-found")
    tenant_id = await _create_tenant_with_profile(f"notfound-{marker[:8]}")
    tender_id, _ = await _create_tender_with_requirements(marker)

    with tenant_scope(tenant_id):
        opportunity_id = await _create_opportunity(tenant_id, tender_id)
        with pytest.raises(AnalysisNotFoundError):
            await get_analysis_with_findings(opportunity_id)
