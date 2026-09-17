"""Identidade: User (perfil por tenant, RLS) e as duas estruturas de bootstrap de autenticacao
que precisam ser consultadas ANTES de se saber o tenant (EmailIndex, RefreshToken).

Por que EmailIndex e RefreshToken sao GLOBAL (sem tenant_id/RLS), ver ADR-0011:
- Login com email+senha nao sabe o tenant de antemao — precisa localizar o usuario por email
  primeiro. Se `users` tivesse RLS exigindo tenant_id no filtro, essa consulta veria zero linhas
  sempre (current_setting indefinido = NULL, e tenant_id = NULL nunca e verdadeiro).
- Em vez de criar uma excecao/bypass na politica de RLS de `users` (superficie de risco
  desnecessaria), mantemos um indice global e minimo so com o que o login precisa
  (email -> user_id, tenant_id), e sempre validamos a senha e o restante do perfil na tabela
  `users` (essa sim, TENANT + RLS) depois de saber o tenant.
- RefreshToken e GLOBAL porque sua seguranca vem de ser um segredo de 256 bits improvavel de
  adivinhar (comparado por hash), nao de um filtro de linha — RLS nao adicionaria protecao real
  aqui e criaria o mesmo problema de bootstrap do login.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base, IdMixin, TenantScopedMixin, TimestampMixin


class Role(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class User(IdMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role"), nullable=False, default=Role.MEMBER
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class EmailIndex(IdMixin, Base):
    """Indice global de login: email (unico em toda a plataforma) -> user_id/tenant_id.

    Nunca contem senha nem qualquer outro dado do perfil — apenas o suficiente para o primeiro
    passo do login. Escrito na mesma transacao tenant-scoped que cria o User (ver
    core/auth/service.py); por nao ter RLS, essa escrita e permitida mesmo dentro de uma
    transacao com `SET LOCAL app.tenant_id` ativo (RLS e por tabela, nao por sessao).
    """

    __tablename__ = "email_index"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class RefreshToken(IdMixin, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
