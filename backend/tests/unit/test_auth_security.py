from __future__ import annotations

import uuid

import jwt
import pytest

from core.auth.models import Role
from core.auth.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from core.config import get_settings


def test_password_hash_roundtrip() -> None:
    password_hash = hash_password("uma-senha-qualquer")
    assert verify_password("uma-senha-qualquer", password_hash)
    assert not verify_password("senha-errada", password_hash)


def test_password_hash_is_not_the_plaintext() -> None:
    assert hash_password("segredo") != "segredo"


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    token = create_access_token(user_id=user_id, tenant_id=tenant_id, role=Role.ADMIN)
    claims = decode_access_token(token)

    assert claims.user_id == user_id
    assert claims.tenant_id == tenant_id
    assert claims.role == Role.ADMIN


def test_decode_rejects_tampered_token() -> None:
    token = create_access_token(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=Role.MEMBER)
    tampered = token[:-4] + "abcd"

    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)


def test_decode_rejects_token_signed_with_different_secret() -> None:
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "role": Role.OWNER.value,
        "type": "access",
    }
    forged = jwt.encode(payload, "chave-errada", algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        decode_access_token(forged)


def test_decode_rejects_expired_token() -> None:
    settings = get_settings()
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "role": Role.OWNER.value,
        "type": "access",
        "exp": 1,  # 1970 — bem expirado
    }
    expired = jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")

    with pytest.raises(InvalidTokenError):
        decode_access_token(expired)


def test_refresh_token_is_hashed_consistently() -> None:
    raw = generate_refresh_token()
    assert hash_refresh_token(raw) == hash_refresh_token(raw)
    assert hash_refresh_token(raw) != raw


def test_refresh_tokens_are_unique() -> None:
    assert generate_refresh_token() != generate_refresh_token()
