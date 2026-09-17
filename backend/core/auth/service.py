"""Orquestracao de autenticacao: identidade (Tenant+User+EmailIndex) e tokens.

Este modulo conhece apenas Tenant/User/RefreshToken/EmailIndex (core.tenancy + core.auth) — a
orquestracao completa de signup, que tambem envolve Subscription (core.billing) e CompanyProfile
(domains.procurement.companies), fica em api/onboarding.py. `core` nao pode depender de
`domains` (ver contrato de camadas em pyproject.toml e ADR-0001): a composicao entre bounded
contexts pertence a camada mais externa (api), nao a um servico de core especifico.

Ver core/auth/models.py para a razao de EmailIndex e RefreshToken serem GLOBAL (sem RLS) — e o
que resolve o problema de "preciso achar o usuario/token antes de saber o tenant".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from core.auth.models import EmailIndex, RefreshToken, Role, User
from core.auth.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from core.db.session import system_session, tenant_session
from core.tenancy.context import tenant_scope
from core.tenancy.models import Tenant


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidRefreshTokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class NewTenantOwner:
    tenant_id: uuid.UUID
    user_id: uuid.UUID


async def issue_token_pair(*, user_id: uuid.UUID, tenant_id: uuid.UUID, role: Role) -> TokenPair:
    access_token = create_access_token(user_id=user_id, tenant_id=tenant_id, role=role)
    raw_refresh = generate_refresh_token()

    async with system_session() as session:
        session.add(
            RefreshToken(
                user_id=user_id,
                tenant_id=tenant_id,
                token_hash=hash_refresh_token(raw_refresh),
                expires_at=refresh_token_expiry(),
            )
        )

    return TokenPair(access_token=access_token, refresh_token=raw_refresh)


async def create_tenant_with_owner(
    *, company_name: str, email: str, password: str
) -> NewTenantOwner:
    """Cria Tenant + User (owner) + entrada no EmailIndex. Nao lida com Subscription nem
    CompanyProfile — ver api/onboarding.py para o fluxo de signup completo.
    """
    normalized_email = email.strip().lower()

    async with system_session() as session:
        existing = await session.execute(
            select(EmailIndex).where(EmailIndex.email == normalized_email)
        )
        if existing.scalar_one_or_none() is not None:
            raise EmailAlreadyRegisteredError(f"Email '{normalized_email}' ja cadastrado")

        tenant = Tenant(name=company_name)
        session.add(tenant)
        await session.flush()
        tenant_id = tenant.id

    with tenant_scope(tenant_id):
        async with tenant_session() as session:
            user = User(
                tenant_id=tenant_id,
                email=normalized_email,
                password_hash=hash_password(password),
                role=Role.OWNER,
            )
            session.add(user)
            await session.flush()
            user_id = user.id

    async with system_session() as session:
        session.add(EmailIndex(email=normalized_email, user_id=user_id, tenant_id=tenant_id))

    return NewTenantOwner(tenant_id=tenant_id, user_id=user_id)


async def login(*, email: str, password: str) -> TokenPair:
    normalized_email = email.strip().lower()

    async with system_session() as session:
        index_result = await session.execute(
            select(EmailIndex).where(EmailIndex.email == normalized_email)
        )
        index_entry = index_result.scalar_one_or_none()
        if index_entry is None:
            raise InvalidCredentialsError("Email ou senha invalidos")
        tenant_id = index_entry.tenant_id
        user_id = index_entry.user_id

    with tenant_scope(tenant_id):
        async with tenant_session() as session:
            user = await session.get(User, user_id)
            if user is None or not user.is_active:
                raise InvalidCredentialsError("Email ou senha invalidos")
            if not verify_password(password, user.password_hash):
                raise InvalidCredentialsError("Email ou senha invalidos")
            role = user.role

    return await issue_token_pair(user_id=user_id, tenant_id=tenant_id, role=role)


async def refresh(*, raw_refresh_token: str) -> TokenPair:
    token_hash = hash_refresh_token(raw_refresh_token)

    async with system_session() as session:
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        token_row = result.scalar_one_or_none()
        if token_row is None:
            raise InvalidRefreshTokenError("Refresh token invalido")
        if token_row.revoked_at is not None:
            raise InvalidRefreshTokenError("Refresh token revogado")
        if token_row.expires_at < datetime.now(UTC):
            raise InvalidRefreshTokenError("Refresh token expirado")

        tenant_id = token_row.tenant_id
        user_id = token_row.user_id
        token_row.revoked_at = datetime.now(UTC)  # rotacao: token usado nunca e reutilizavel

    with tenant_scope(tenant_id):
        async with tenant_session() as session:
            user = await session.get(User, user_id)
            if user is None or not user.is_active:
                raise InvalidRefreshTokenError("Usuario nao encontrado ou inativo")
            role = user.role

    return await issue_token_pair(user_id=user_id, tenant_id=tenant_id, role=role)


async def logout(*, raw_refresh_token: str) -> None:
    token_hash = hash_refresh_token(raw_refresh_token)
    async with system_session() as session:
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        token_row = result.scalar_one_or_none()
        if token_row is not None and token_row.revoked_at is None:
            token_row.revoked_at = datetime.now(UTC)
