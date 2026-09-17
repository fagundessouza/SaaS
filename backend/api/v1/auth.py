"""Endpoints de autenticacao: signup, login, refresh, logout.

`signup` substitui o bootstrap aberto `POST /v1/tenants` da Fase 1 — criar um tenant agora
sempre vem acompanhado de um usuario dono, uma assinatura trial e um perfil de empresa.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from api.onboarding import signup as signup_service
from core.auth.service import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from core.auth.service import login as login_service
from core.auth.service import logout as logout_service
from core.auth.service import refresh as refresh_service

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class SignupRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=255)
    cnpj: str | None = Field(default=None, max_length=18)


class SignupResponse(TokenPairResponse):
    tenant_id: UUID
    user_id: UUID
    company_profile_id: UUID


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/signup", response_model=SignupResponse, status_code=201)
async def signup(payload: SignupRequest) -> SignupResponse:
    try:
        result = await signup_service(
            company_name=payload.company_name,
            email=payload.email,
            password=payload.password,
            cnpj=payload.cnpj,
        )
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return SignupResponse(
        tenant_id=result.tenant_id,
        user_id=result.user_id,
        company_profile_id=result.company_profile_id,
        access_token=result.tokens.access_token,
        refresh_token=result.tokens.refresh_token,
    )


@router.post("/login", response_model=TokenPairResponse)
async def login(payload: LoginRequest) -> TokenPairResponse:
    try:
        tokens = await login_service(email=payload.email, password=payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return TokenPairResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(payload: RefreshRequest) -> TokenPairResponse:
    try:
        tokens = await refresh_service(raw_refresh_token=payload.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return TokenPairResponse(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/logout", status_code=204)
async def logout(payload: RefreshRequest) -> None:
    await logout_service(raw_refresh_token=payload.refresh_token)
