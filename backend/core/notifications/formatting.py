"""Formatacao deterministica de mensagem (assunto + corpo) a partir de topico + payload de
evento — nunca gerada por um LLM (ai_platform/llm nao existe ainda, Fase 9). Compartilhada por
todo canal para que o texto seja consistente entre email/web push.

Catalogo de topicos conhecidos (ver docs/EVENT_AND_NOTIFICATION_ARCHITECTURE.md, tabela
"Catalogo de eventos de dominio") — um topico sem entrada aqui ainda gera uma mensagem genérica
(`_generic`), nunca uma excecao: um evento novo nao pode derrubar o consumidor.
"""

from __future__ import annotations

from collections.abc import Callable

_Payload = dict[str, object]


def _tender_updated(payload: _Payload) -> tuple[str, str]:
    identifier = payload.get("external_id", payload.get("tender_id"))
    return (
        "Edital retificado",
        f"O edital que você acompanha (Tender {identifier}) foi retificado (nova versão "
        f"{payload.get('version_number', '?')}). Revise as mudanças antes de submeter sua "
        "proposta.",
    )


def _opportunity_matched(payload: _Payload) -> tuple[str, str]:
    return (
        "Nova oportunidade encontrada",
        f"Um novo edital compatível com o seu perfil foi encontrado (Tender "
        f"{payload.get('tender_id')}). Acesse o radar para ver os detalhes do match.",
    )


def _analysis_completed(payload: _Payload) -> tuple[str, str]:
    return (
        "Dossiê de oportunidade pronto",
        f"O dossiê da oportunidade {payload.get('opportunity_id')} foi gerado. Confira os "
        "requisitos pendentes antes de decidir participar.",
    )


def _certificate_expiring(payload: _Payload) -> tuple[str, str]:
    return (
        "Certidão próxima do vencimento",
        f"A certidão '{payload.get('certificate_name')}' vence em "
        f"{payload.get('expires_at')}. Providencie a renovação para não perder habilitação em "
        "editais futuros.",
    )


def _generic(payload: _Payload) -> tuple[str, str]:
    return ("Nova notificação", "Você tem uma nova notificação na plataforma.")


_FORMATTERS: dict[str, Callable[[_Payload], tuple[str, str]]] = {
    "TenderUpdated": _tender_updated,
    "OpportunityMatched": _opportunity_matched,
    "AnalysisCompleted": _analysis_completed,
    "CertificateExpiring": _certificate_expiring,
}


def format_message(topic: str, payload: _Payload) -> tuple[str, str]:
    formatter = _FORMATTERS.get(topic, _generic)
    return formatter(payload)
