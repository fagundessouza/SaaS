"""Gera o dossie (Analysis + Finding + Evidence) de uma Opportunity — cruza os Requirement do
edital (Fase 6, GLOBAL) contra o que o tenant declarou ter (Certificate/Attestation, Fase 8).

Fronteira regra-vs-IA (ADR-0007):
- Requirement de categoria FISCAL/JURIDICA/ECONOMICO_FINANCEIRA -> cruzado contra Certificate por
  REGRA pura: existe um Certificate da mesma categoria? Esta dentro da validade (comparacao de
  data)? Nenhuma chamada de IA — mesma linha do ADR-0007 ("prazos, comparacao de datas" e
  "validade de CNPJ/CNAE" -> regra deterministica).
- Requirement de categoria TECNICA -> cruzado contra Attestation por IA (embedding): nao ha campo
  estruturado equivalente a "vencimento" para experiencia tecnica, a pergunta e semantica ("este
  atestado cobre o que este requisito pede?") — mesmo EmbeddingProvider self-hosted da Fase 5,
  mesmo padrao ja usado em requirements_service.py (Fase 6) e matching.py (Fase 7).

Nunca gerada automaticamente para toda Opportunity descoberta (ver
docs/00-CRITICAL_ANALYSIS.md item 5 da secao 6) — so quando o usuario aprofunda numa oportunidade
especifica, via `generate_analysis`. Regenerar substitui a analise anterior (nao ha historico de
versoes de Analysis nesta fase, mesma decisao ja tomada para TenderItem na Fase 6).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import delete, select

from ai_platform.embeddings.fastembed_provider import get_embedding_provider
from core.config import get_settings
from core.db.session import system_session, tenant_session
from core.observability.logging import get_logger
from core.observability.metrics import analyses_generated_total, findings_by_status_total
from domains.procurement.analysis.models import (
    Analysis,
    Evidence,
    EvidenceKind,
    Finding,
    FindingSeverity,
    FindingStatus,
)
from domains.procurement.companies.models import Attestation, Certificate, CompanyProfile
from domains.procurement.opportunities.models import Opportunity
from domains.procurement.tenders.models import Requirement, RequirementCategory

logger = get_logger(__name__)


class OpportunityNotFoundError(Exception):
    pass


class AnalysisNotFoundError(Exception):
    pass


class CompanyProfileNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class _FindingDraft:
    requirement_id: uuid.UUID
    category: RequirementCategory
    status: FindingStatus
    severity: FindingSeverity
    summary: str
    # Evidencia do proprio requisito — sempre presente (ver docstring do modulo).
    document_version_id: uuid.UUID
    section: str | None
    page_start: int
    page_end: int
    requirement_excerpt: str
    # Evidencia secundaria opcional (o que o tenant tem que satisfaz/nao satisfaz o requisito).
    certificate_id: uuid.UUID | None = None
    certificate_description: str | None = None
    attestation_id: uuid.UUID | None = None
    attestation_description: str | None = None


def _category_label(category: RequirementCategory | str) -> str:
    """`Requirement.category`/`Certificate.category` sao colunas `String` pura, nao `Enum` (ver
    domains/procurement/tenders/models.py) — um valor lido de volta do banco chega como `str`
    puro, nao uma instancia de `RequirementCategory`, entao `.value` quebraria (achado no smoke
    test manual desta fase, ver docs/phase-reports/FASE_8_REPORT.md). `str(x)` funciona igual
    para os dois casos, porque `StrEnum.__str__` retorna o proprio valor."""
    return str(category)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _evaluate_certificate_requirement(
    requirement: Requirement, certificates: list[Certificate], today: date
) -> tuple[FindingStatus, FindingSeverity, str, Certificate | None]:
    candidates = [c for c in certificates if c.category == requirement.category]
    if not candidates:
        return (
            FindingStatus.MISSING,
            FindingSeverity.BLOCKING,
            f"Nenhuma certidao de categoria '{_category_label(requirement.category)}' cadastrada "
            "para este requisito.",
            None,
        )

    valid = [c for c in candidates if c.expires_at is None or c.expires_at >= today]
    if valid:
        # Entre validas, a de vencimento mais distante — a mais "solida" para citar.
        chosen = max(valid, key=lambda c: c.expires_at or date.max)
        validade = (
            "sem data de vencimento"
            if chosen.expires_at is None
            else f"valida ate {chosen.expires_at.isoformat()}"
        )
        return (
            FindingStatus.MET,
            FindingSeverity.INFO,
            f"Certidao '{chosen.name}' cadastrada e {validade}.",
            chosen,
        )

    # Nenhuma valida: reporta a de vencimento mais recente (a mais proxima de ser regularizavel).
    chosen = max(candidates, key=lambda c: c.expires_at or date.min)
    assert chosen.expires_at is not None  # garantido: so chega aqui quem nao esta em `valid`
    return (
        FindingStatus.EXPIRED,
        FindingSeverity.BLOCKING,
        f"Certidao '{chosen.name}' esta vencida desde {chosen.expires_at.isoformat()}.",
        chosen,
    )


async def _evaluate_attestation_requirement(
    requirement: Requirement, attestations: list[Attestation]
) -> tuple[FindingStatus, FindingSeverity, str, Attestation | None]:
    if not attestations:
        return (
            FindingStatus.MISSING,
            FindingSeverity.BLOCKING,
            "Nenhum atestado de capacidade tecnica cadastrado para este requisito.",
            None,
        )

    settings = get_settings()
    provider = get_embedding_provider()
    texts = [requirement.description, *[a.object_description for a in attestations]]
    vectors = await provider.embed(texts)
    requirement_vector, attestation_vectors = vectors[0], vectors[1:]

    scores = [_cosine_similarity(requirement_vector, vector) for vector in attestation_vectors]
    best_index = max(range(len(scores)), key=lambda i: scores[i])
    best_score = scores[best_index]
    best = attestations[best_index]

    if best_score >= settings.analysis_attestation_met_threshold:
        return (
            FindingStatus.MET,
            FindingSeverity.INFO,
            f"Atestado de '{best.issuing_org}' identificado como equivalente a este requisito "
            f"(similaridade {best_score:.2f}).",
            best,
        )
    if best_score >= settings.analysis_attestation_review_threshold:
        return (
            FindingStatus.NEEDS_REVIEW,
            FindingSeverity.WARNING,
            f"Atestado de '{best.issuing_org}' e possivelmente equivalente a este requisito "
            f"(similaridade {best_score:.2f}) — revisao humana recomendada.",
            best,
        )
    return (
        FindingStatus.MISSING,
        FindingSeverity.BLOCKING,
        "Nenhum atestado cadastrado parece cobrir este requisito "
        f"(melhor similaridade {best_score:.2f}, abaixo do limiar minimo).",
        None,
    )


async def _build_findings(
    requirements: list[Requirement],
    certificates: list[Certificate],
    attestations: list[Attestation],
) -> list[_FindingDraft]:
    today = datetime.now(UTC).date()
    drafts: list[_FindingDraft] = []

    for requirement in requirements:
        certificate: Certificate | None = None
        attestation: Attestation | None = None

        if requirement.category == RequirementCategory.TECNICA:
            status, severity, summary, attestation = await _evaluate_attestation_requirement(
                requirement, attestations
            )
        else:
            status, severity, summary, certificate = _evaluate_certificate_requirement(
                requirement, certificates, today
            )

        drafts.append(
            _FindingDraft(
                requirement_id=requirement.id,
                category=requirement.category,
                status=status,
                severity=severity,
                summary=summary,
                document_version_id=requirement.document_version_id,
                section=requirement.section,
                page_start=requirement.page_start,
                page_end=requirement.page_end,
                requirement_excerpt=requirement.description,
                certificate_id=certificate.id if certificate else None,
                certificate_description=(
                    f"Certidao '{certificate.name}' "
                    f"(categoria {_category_label(certificate.category)})."
                    if certificate
                    else None
                ),
                attestation_id=attestation.id if attestation else None,
                attestation_description=(
                    f"Atestado de '{attestation.issuing_org}': {attestation.object_description}"
                    if attestation
                    else None
                ),
            )
        )

    return drafts


async def generate_analysis(opportunity_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session() as session:
        opportunity = await session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(str(opportunity_id))
        tenant_id = opportunity.tenant_id
        tender_id = opportunity.tender_id

        profile_result = await session.execute(
            select(CompanyProfile).where(CompanyProfile.tenant_id == tenant_id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile is None:
            raise CompanyProfileNotFoundError(str(tenant_id))
        company_profile_id = profile.id

        certificates = list(
            (
                await session.execute(
                    select(Certificate).where(Certificate.company_profile_id == company_profile_id)
                )
            )
            .scalars()
            .all()
        )
        attestations = list(
            (
                await session.execute(
                    select(Attestation).where(
                        Attestation.company_profile_id == company_profile_id
                    )
                )
            )
            .scalars()
            .all()
        )

    async with system_session() as session:
        requirements = list(
            (
                await session.execute(
                    select(Requirement).where(Requirement.tender_id == tender_id)
                )
            )
            .scalars()
            .all()
        )

    drafts = await _build_findings(requirements, certificates, attestations)

    async with tenant_session() as session:
        existing = await session.execute(
            select(Analysis.id).where(Analysis.opportunity_id == opportunity_id)
        )
        existing_id = existing.scalar_one_or_none()
        if existing_id is not None:
            # Regenerar substitui: sem historico de versoes de Analysis nesta fase (ver
            # docstring do modulo). Ordem de delete respeita as FKs (evidences -> findings ->
            # analysis), sem depender de ON DELETE CASCADE no schema.
            await session.execute(
                delete(Evidence).where(
                    Evidence.finding_id.in_(
                        select(Finding.id).where(Finding.analysis_id == existing_id)
                    )
                )
            )
            await session.execute(delete(Finding).where(Finding.analysis_id == existing_id))
            await session.execute(delete(Analysis).where(Analysis.id == existing_id))

        analysis = Analysis(
            tenant_id=tenant_id, opportunity_id=opportunity_id, generated_at=datetime.now(UTC)
        )
        session.add(analysis)
        await session.flush()

        for draft in drafts:
            finding = Finding(
                tenant_id=tenant_id,
                analysis_id=analysis.id,
                requirement_id=draft.requirement_id,
                category=draft.category,
                status=draft.status,
                severity=draft.severity,
                summary=draft.summary,
            )
            session.add(finding)
            await session.flush()

            session.add(
                Evidence(
                    tenant_id=tenant_id,
                    finding_id=finding.id,
                    kind=EvidenceKind.REQUIREMENT_TEXT,
                    description=f'Trecho do edital: "{draft.requirement_excerpt[:200]}"',
                    document_version_id=draft.document_version_id,
                    section=draft.section,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    excerpt=draft.requirement_excerpt,
                )
            )
            if draft.certificate_id is not None:
                session.add(
                    Evidence(
                        tenant_id=tenant_id,
                        finding_id=finding.id,
                        kind=EvidenceKind.CERTIFICATE_DATA,
                        description=draft.certificate_description or "",
                        certificate_id=draft.certificate_id,
                    )
                )
            if draft.attestation_id is not None:
                session.add(
                    Evidence(
                        tenant_id=tenant_id,
                        finding_id=finding.id,
                        kind=EvidenceKind.ATTESTATION_DATA,
                        description=draft.attestation_description or "",
                        attestation_id=draft.attestation_id,
                    )
                )

        analysis_id = analysis.id

    analyses_generated_total.inc()
    for draft in drafts:
        findings_by_status_total.labels(status=draft.status.value).inc()
    logger.info(
        "analysis.generated",
        opportunity_id=str(opportunity_id),
        analysis_id=str(analysis_id),
        findings=len(drafts),
    )
    return analysis_id


async def get_analysis_with_findings(
    opportunity_id: uuid.UUID,
) -> tuple[Analysis, list[tuple[Finding, list[Evidence]]]]:
    """Le a Analysis mais recente de uma Opportunity com seus Finding + Evidence — nunca gera,
    so le o que `generate_analysis` ja persistiu (ver `AnalysisNotFoundError`)."""
    async with tenant_session() as session:
        analysis_result = await session.execute(
            select(Analysis).where(Analysis.opportunity_id == opportunity_id)
        )
        analysis = analysis_result.scalar_one_or_none()
        if analysis is None:
            raise AnalysisNotFoundError(str(opportunity_id))

        findings = list(
            (
                await session.execute(
                    select(Finding)
                    .where(Finding.analysis_id == analysis.id)
                    .order_by(Finding.severity, Finding.category)
                )
            )
            .scalars()
            .all()
        )

        evidence_result = await session.execute(
            select(Evidence).where(
                Evidence.finding_id.in_([finding.id for finding in findings])
            )
        )
        evidence_by_finding: dict[uuid.UUID, list[Evidence]] = {}
        for evidence in evidence_result.scalars().all():
            evidence_by_finding.setdefault(evidence.finding_id, []).append(evidence)

        return analysis, [
            (finding, evidence_by_finding.get(finding.id, [])) for finding in findings
        ]
