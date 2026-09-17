"""Endpoints de usuario: perfil proprio e convite de novos usuarios no tenant.

NOTA DE ESCOPO (Fase 2): "convidar" aqui cria o usuario com a senha ja definida pelo
owner/admin que convida (sem fluxo de e-mail de convite/definicao de senha pelo proprio
usuario) — enviar e-mail e responsabilidade do Notification Engine (Fase 10), fora do escopo
desta fase. Documentado para nao ser confundido com uma omissao silenciosa.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from api.deps import CurrentUser, get_current_user, require_role
from core.auth.models import EmailIndex, Role, User
from core.auth.security import hash_password
from core.billing.service import (
    NoActiveSubscriptionError,
    UserLimitReachedError,
    ensure_user_limit_not_reached,
    get_active_plan,
)
from core.db.session import system_session, tenant_session

router = APIRouter(prefix="/v1/users", tags=["users"])


class UserResponse(BaseModel):
    id: UUID
    email: str
    role: Role
    is_active: bool

    model_config = {"from_attributes": True}


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=255)
    role: Role = Role.MEMBER


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser = Depends(get_current_user)) -> User:
    async with tenant_session() as session:
        user = await session.get(User, current_user.user_id)
        assert user is not None
        return user


@router.get("", response_model=list[UserResponse])
async def list_users(
    current_user: CurrentUser = Depends(require_role(Role.OWNER, Role.ADMIN)),
) -> list[User]:
    async with tenant_session() as session:
        result = await session.execute(select(User).where(User.tenant_id == current_user.tenant_id))
        return list(result.scalars().all())


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    payload: CreateUserRequest,
    current_user: CurrentUser = Depends(require_role(Role.OWNER, Role.ADMIN)),
) -> User:
    normalized_email = payload.email.strip().lower()

    async with system_session() as session:
        existing = await session.execute(
            select(EmailIndex).where(EmailIndex.email == normalized_email)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Email ja cadastrado")

    async with tenant_session() as session:
        try:
            plan = await get_active_plan(session, current_user.tenant_id)
            await ensure_user_limit_not_reached(session, current_user.tenant_id, plan)
        except NoActiveSubscriptionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except UserLimitReachedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        user = User(
            tenant_id=current_user.tenant_id,
            email=normalized_email,
            password_hash=hash_password(payload.password),
            role=payload.role,
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)
        user_id = user.id

    async with system_session() as session:
        session.add(
            EmailIndex(email=normalized_email, user_id=user_id, tenant_id=current_user.tenant_id)
        )

    return user
