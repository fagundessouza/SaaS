"""Testes puros (sem DB/rede) de core/notifications/formatting.py — formatacao deterministica
de mensagem a partir de topico + payload, nunca gerada por LLM."""

from __future__ import annotations

from core.notifications.formatting import format_message


def test_tender_updated_mentions_external_id_and_version() -> None:
    subject, body = format_message(
        "TenderUpdated",
        {"tender_id": "abc", "external_id": "12345-1-000001/2026", "version_number": 2},
    )

    assert subject == "Edital retificado"
    assert "12345-1-000001/2026" in body
    assert "2" in body


def test_tender_updated_falls_back_to_tender_id_without_external_id() -> None:
    _, body = format_message("TenderUpdated", {"tender_id": "abc123"})

    assert "abc123" in body


def test_opportunity_matched_mentions_tender_id() -> None:
    subject, body = format_message("OpportunityMatched", {"tender_id": "abc123"})

    assert subject == "Nova oportunidade encontrada"
    assert "abc123" in body


def test_analysis_completed_mentions_opportunity_id() -> None:
    subject, body = format_message("AnalysisCompleted", {"opportunity_id": "opp-1"})

    assert "opp-1" in body


def test_certificate_expiring_mentions_name_and_date() -> None:
    subject, body = format_message(
        "CertificateExpiring", {"certificate_name": "CND Federal", "expires_at": "2026-10-01"}
    )

    assert "CND Federal" in body
    assert "2026-10-01" in body


def test_unknown_topic_falls_back_to_generic_message_without_raising() -> None:
    subject, body = format_message("SomeFutureTopicNotYetHandled", {"anything": 1})

    assert subject
    assert body
