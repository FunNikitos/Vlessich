"""Admin authentication: bcrypt password hashing + HS256 JWT (Stage 2 T4).

- Password storage: ``bcrypt`` at cost from ``settings.admin_bcrypt_cost``.
- Access token: HS256 with ``settings.admin_jwt_secret``, TTL from
  ``settings.admin_jwt_ttl_sec``. Claims: ``sub`` (admin_user_id),
  ``role``, ``iat``, ``exp``.
- No refresh token in Stage 2 — re-login after access expiry. Refresh
  lands in Stage 4 together with the Admin UI.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated, Literal

import bcrypt
import jwt
from fastapi import Depends, Header, status

from app.config import get_settings
from app.errors import ApiCode, api_error

Role = Literal["superadmin", "support", "readonly"]
JWT_ALG = "HS256"


@dataclass(slots=True, frozen=True)
class AdminClaims:
    sub: str  # admin_user_id (UUID str)
    role: Role
    iat: int
    exp: int


def hash_password(plain: str) -> str:
    cost = get_settings().admin_bcrypt_cost
    salt = bcrypt.gensalt(rounds=cost)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(admin_user_id: str, role: Role) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": admin_user_id,
        "role": role,
        "iat": now,
        "exp": now + settings.admin_jwt_ttl_sec,
    }
    return jwt.encode(
        payload, settings.admin_jwt_secret.get_secret_value(), algorithm=JWT_ALG
    )


def decode_token(token: str) -> AdminClaims:
    settings = get_settings()
    try:
        decoded = jwt.decode(
            token,
            settings.admin_jwt_secret.get_secret_value(),
            algorithms=[JWT_ALG],
        )
    except jwt.ExpiredSignatureError as exc:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_SIG, "admin token expired"
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_SIG, "admin token invalid"
        ) from exc

    role = decoded.get("role")
    if role not in ("superadmin", "support", "readonly"):
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_SIG, "admin token invalid role"
        )
    sub = decoded.get("sub")
    if not isinstance(sub, str):
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_SIG, "admin token invalid sub"
        )
    return AdminClaims(
        sub=sub, role=role, iat=int(decoded["iat"]), exp=int(decoded["exp"])
    )


def _extract_bearer(authorization: str) -> str:
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_SIG, "missing bearer token"
        )
    return parts[1]


async def require_admin(
    authorization: Annotated[str, Header(alias="Authorization")] = "",
) -> AdminClaims:
    token = _extract_bearer(authorization)
    return decode_token(token)


def require_admin_role(*allowed: Role):
    """Dependency factory: require the admin's role to be in ``allowed``."""

    async def _dep(claims: Annotated[AdminClaims, Depends(require_admin)]) -> AdminClaims:
        if claims.role not in allowed:
            raise api_error(status.HTTP_403_FORBIDDEN, ApiCode.BAD_SIG, "forbidden")
        return claims

    return _dep


__all__ = [
    "AdminClaims",
    "Role",
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_token",
    "require_admin",
    "require_admin_role",
]
