"""Testes puros (sem DB/rede) da regra deterministica de cruzamento Requirement x Certificate
(ver domains/procurement/analysis/service.py). O caminho de Attestation (embedding) e testado
contra fastembed real em tests/integration/test_analysis_service.py.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from domains.procurement.analysis.models import FindingSeverity, FindingStatus
from domains.procurement.analysis.service import (
    _category_label,
    _evaluate_certificate_requirement,
)
from domains.procurement.companies.models import Certificate
from domains.procurement.tenders.models import Requirement, RequirementCategory

_TODAY = date(2026, 1, 1)


def _requirement(category: RequirementCategory) -> Requirement:
    return Requirement(
        id=uuid.uuid4(),
        tender_id=uuid.uuid4(),
        category=category,
        description="requisito de teste",
        confidence=1.0,
        document_version_id=uuid.uuid4(),
        chunk_index=0,
        section="secao de teste",
        page_start=1,
        page_end=1,
    )


def _certificate(
    category: RequirementCategory, expires_at: date | None, name: str = "Certidao Teste"
) -> Certificate:
    return Certificate(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        company_profile_id=uuid.uuid4(),
        category=category,
        name=name,
        issued_at=None,
        expires_at=expires_at,
    )


def test_missing_when_no_certificate_of_the_category_exists() -> None:
    requirement = _requirement(RequirementCategory.JURIDICA)

    status, severity, summary, certificate = _evaluate_certificate_requirement(
        requirement, certificates=[], today=_TODAY
    )

    assert status == FindingStatus.MISSING
    assert severity == FindingSeverity.BLOCKING
    assert "juridica" in summary
    assert certificate is None


def test_missing_when_only_certificate_of_a_different_category_exists() -> None:
    requirement = _requirement(RequirementCategory.JURIDICA)
    certificates = [_certificate(RequirementCategory.FISCAL, expires_at=None)]

    status, _, _, certificate = _evaluate_certificate_requirement(
        requirement, certificates, today=_TODAY
    )

    assert status == FindingStatus.MISSING
    assert certificate is None


def test_met_when_certificate_has_no_expiry_date() -> None:
    requirement = _requirement(RequirementCategory.JURIDICA)
    certificate = _certificate(RequirementCategory.JURIDICA, expires_at=None)

    status, severity, summary, chosen = _evaluate_certificate_requirement(
        requirement, [certificate], today=_TODAY
    )

    assert status == FindingStatus.MET
    assert severity == FindingSeverity.INFO
    assert "sem data de vencimento" in summary
    assert chosen is certificate


def test_met_when_certificate_expires_in_the_future() -> None:
    requirement = _requirement(RequirementCategory.FISCAL)
    certificate = _certificate(RequirementCategory.FISCAL, expires_at=_TODAY + timedelta(days=1))

    status, _, summary, chosen = _evaluate_certificate_requirement(
        requirement, [certificate], today=_TODAY
    )

    assert status == FindingStatus.MET
    assert chosen is certificate
    assert certificate.expires_at is not None
    assert certificate.expires_at.isoformat() in summary


def test_expired_when_certificate_expires_in_the_past() -> None:
    requirement = _requirement(RequirementCategory.FISCAL)
    certificate = _certificate(RequirementCategory.FISCAL, expires_at=_TODAY - timedelta(days=1))

    status, severity, summary, chosen = _evaluate_certificate_requirement(
        requirement, [certificate], today=_TODAY
    )

    assert status == FindingStatus.EXPIRED
    assert severity == FindingSeverity.BLOCKING
    assert chosen is certificate
    assert "vencida" in summary


def test_expired_certificate_valid_on_the_exact_expiry_date() -> None:
    """expires_at == hoje ainda conta como valido (>=, nao >) — a certidao so vira invalida no
    dia seguinte ao vencimento."""
    requirement = _requirement(RequirementCategory.FISCAL)
    certificate = _certificate(RequirementCategory.FISCAL, expires_at=_TODAY)

    status, _, _, _ = _evaluate_certificate_requirement(requirement, [certificate], today=_TODAY)

    assert status == FindingStatus.MET


def test_prefers_valid_certificate_over_expired_one_of_same_category() -> None:
    requirement = _requirement(RequirementCategory.FISCAL)
    expired = _certificate(
        RequirementCategory.FISCAL, expires_at=_TODAY - timedelta(days=10), name="Vencida"
    )
    valid = _certificate(
        RequirementCategory.FISCAL, expires_at=_TODAY + timedelta(days=10), name="Valida"
    )

    status, _, _, chosen = _evaluate_certificate_requirement(
        requirement, [expired, valid], today=_TODAY
    )

    assert status == FindingStatus.MET
    assert chosen is valid


def test_category_label_handles_raw_string_from_db_round_trip() -> None:
    """Requirement.category/Certificate.category sao colunas String pura, nao Enum — um valor
    lido de volta do banco chega como str puro, nao uma instancia de RequirementCategory (achado
    no smoke test manual desta fase). `_category_label` precisa funcionar para os dois casos."""
    assert _category_label(RequirementCategory.FISCAL) == "fiscal"
    assert _category_label("fiscal") == "fiscal"
