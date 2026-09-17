"""Funcoes puras de criptografia — sem acesso a banco, sem FastAPI. Ver core/auth/service.py
para a orquestracao com persistencia.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from core.auth.models import Role
from core.config import get_settings

_JWT_ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    pass


def hash_password(raw_password: str) -> str:
    return bcrypt.hashpw(raw_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(raw_password.encode("utf-8"), password_hash.encode("utf-8"))


@dataclass(frozen=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: Role


def create_access_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID, role: Role) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role.value,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> AccessTokenClaims:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Access token invalido ou expirado") from exc

    if payload.get("type") != "access":
        raise InvalidTokenError("Token nao e um access token")

    try:
        return AccessTokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            tenant_id=uuid.UUID(payload["tenant_id"]),
            role=Role(payload["role"]),
        )
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("Claims do access token malformadas") from exc


def generate_refresh_token() -> str:
    """Segredo opaco (nao-JWT) de 256 bits — a seguranca vem de ser improvavel de adivinhar,
    nao de qualquer estrutura interpretavel (ver core/auth/models.py sobre RefreshToken)."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def refresh_token_expiry() -> datetime:
    settings = get_settings()
    return datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days)
