"""Tests for admin auth (bcrypt + JWT) — Stage 2 T4."""
from __future__ import annotations

import os

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")  # fast for tests
os.environ.setdefault(
    "API_DATABASE_URL", "postgresql+asyncpg://vlessich:vlessich@localhost:5432/vlessich"
)

import time

import pytest

from app.auth.admin import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.errors import ApiCode


def test_hash_and_verify_round_trip() -> None:
    h = hash_password("correct horse")
    assert verify_password("correct horse", h)
    assert not verify_password("wrong", h)


def test_hash_is_not_plaintext() -> None:
    h = hash_password("secret123")
    assert h != "secret123"
    assert h.startswith("$2")  # bcrypt


def test_token_round_trip() -> None:
    token = create_access_token("abc-123", "superadmin")
    claims = decode_token(token)
    assert claims.sub == "abc-123"
    assert claims.role == "superadmin"
    assert claims.exp > claims.iat


def test_expired_token_rejected() -> None:
    # Monkey-patch exp by crafting a token with past exp via time.sleep not
    # feasible — use pyjwt directly.
    import jwt

    from app.config import get_settings

    payload = {
        "sub": "abc",
        "role": "readonly",
        "iat": int(time.time()) - 7200,
        "exp": int(time.time()) - 3600,
    }
    tok = jwt.encode(
        payload,
        get_settings().admin_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(Exception) as exc_info:
        decode_token(tok)
    assert exc_info.value.detail["code"] == ApiCode.BAD_SIG.value  # type: ignore[attr-defined]


def test_tampered_token_rejected() -> None:
    token = create_access_token("abc", "support")
    tampered = token[:-4] + "AAAA"
    with pytest.raises(Exception) as exc_info:
        decode_token(tampered)
    assert exc_info.value.detail["code"] == ApiCode.BAD_SIG.value  # type: ignore[attr-defined]


def test_invalid_role_in_token_rejected() -> None:
    import jwt

    from app.config import get_settings

    payload = {
        "sub": "abc",
        "role": "god",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
    }
    tok = jwt.encode(
        payload,
        get_settings().admin_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(Exception):
        decode_token(tok)
