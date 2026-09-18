"""AssistantSession / AssistantMessage (Fase 9, ver docs/UX_AND_ASSISTANT_SPEC.md e
docs/DOMAIN_MODEL.md). `AssistantSession` amarra um usuario a um contexto (hoje so
`opportunity_id`, ver "Contexto que o assistente recebe automaticamente" na spec — a tela atual
e o edital ficam implicitos por essa referencia). `AssistantMessage` e DERIVADA de
AssistantSession.

Memoria de longo prazo do assistente NAO e uma entidade propria aqui (ver DOMAIN_MODEL.md:
"nao um cerebro paralelo desincronizado do resto do dominio") — o historico de uma
AssistantSession e so o registro da conversa daquele contexto, nao um sistema de memoria
cross-sessao (isso dependeria de TenantKnowledge/Feedback/Decision, que nao existem ainda,
Fase 14).
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, IdMixin, TenantScopedMixin, TimestampMixin


class AssistantMessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class AssistantAction(enum.StrEnum):
    """Cada acao e uma chamada de ferramenta deterministica no backend, nunca um prompt livre
    reinterpretado (ver UX_AND_ASSISTANT_SPEC.md: "o texto do botao e uma ancora de intencao,
    nao uma sugestao de frase para o usuario digitar" — mitiga o risco de "Fake AI" da secao 7
    da analise critica). 3 das ~6 acoes sugeridas na spec (escopo minimo da Fase 9, "3-4 acoes,
    nao todas de uma vez"): as que ja tem dado real disponivel (Fase 6/8), sem depender de
    Legal/Pricing (Fase 12, ainda nao implementada)."""

    MISSING_REQUIREMENTS = "missing_requirements"  # "O que esta faltando?" — exigido pelo
    # criterio de saida da Fase 9 (ver IMPLEMENTATION_ROADMAP.md).
    UNDERSTAND_TENDER = "understand_tender"  # "Entender edital"
    EXPLAIN_REQUIREMENT = "explain_requirement"  # "Explicar este requisito"


class AssistantSession(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "assistant_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=False, index=True
    )


class AssistantMessage(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "assistant_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assistant_sessions.id"), nullable=False, index=True
    )
    role: Mapped[AssistantMessageRole] = mapped_column(
        Enum(AssistantMessageRole, name="assistant_message_role"), nullable=False
    )
    action: Mapped[AssistantAction | None] = mapped_column(
        Enum(AssistantAction, name="assistant_action"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Citacoes estruturadas (finding_id, requirement_id, secao, pagina, etc.) — sempre geradas
    # por query deterministica, nunca extraidas do texto do LLM (ver ADR-0007: o LLM sintetiza
    # linguagem natural, o dado estruturado vem do banco). Vazio para mensagens de role USER.
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
