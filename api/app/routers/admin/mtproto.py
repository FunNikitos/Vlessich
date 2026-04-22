"""Admin MTProto rotation (Stage 8).

``POST /admin/mtproto/rotate`` — superadmin-only. Mints a fresh
random secret (32-hex), REVOKEs the current ACTIVE shared secret if
any, and inserts the new one. Response carries everything the
operator needs to update ``mtg/config.toml`` and restart the mtg
container; we do not touch mtg ourselves in this stage (config is on
a separate VPS, see TZ §9A.8).

Audit trail: ``AuditLog(action="mtproto_rotated")`` carries the new
row id and cloak (never the secret material).
"""
from __future__ import annotations

import secrets as pysecrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import AdminClaims, require_admin_role
from app.config import get_settings
from app.db import get_session
from app.errors import ApiCode, api_error
from app.models import AuditLog, MtprotoSecret

router = APIRouter(prefix="/admin/mtproto", tags=["admin"])


class RotateIn(BaseModel):
    """Optional override for the cloak domain bound to the new secret."""

    cloak_domain: str | None = Field(
        default=None,
        min_length=4,
        max_length=255,
        description="If set, replaces API_MTG_SHARED_CLOAK for this rotation.",
    )


class RotateOut(BaseModel):
    secret_id: str
    secret_hex: str
    cloak_domain: str
    full_secret: str = Field(
        ...,
        description="Full ee-prefixed mtg secret: ee + 32hex + hex(cloak).",
    )
    config_line: str = Field(
        ...,
        description="Drop-in replacement for the `secret = \"...\"` line in mtg/config.toml.",
    )
    host: str
    port: int
    rotated_at: datetime
    revoked_secret_id: str | None


def _full_secret(secret_hex: str, cloak: str) -> str:
    return f"ee{secret_hex}{cloak.encode().hex()}"


@router.post(
    "/rotate",
    response_model=RotateOut,
    status_code=status.HTTP_200_OK,
)
async def rotate(
    payload: RotateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    claims: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> RotateOut:
    settings = get_settings()
    cloak = (payload.cloak_domain or settings.mtg_shared_cloak).strip()
    if not cloak:
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            ApiCode.INVALID_REQUEST,
            "cloak_domain пуст.",
        )

    new_hex = pysecrets.token_hex(16)

    async with session.begin():
        current = await session.scalar(
            select(MtprotoSecret)
            .where(
                MtprotoSecret.scope == "shared",
                MtprotoSecret.status == "ACTIVE",
            )
            .with_for_update()
        )
        revoked_id: str | None = None
        if current is not None:
            current.status = "REVOKED"
            revoked_id = str(current.id)

        fresh = MtprotoSecret(
            secret_hex=new_hex,
            cloak_domain=cloak,
            scope="shared",
            status="ACTIVE",
        )
        session.add(fresh)
        await session.flush()

        session.add(
            AuditLog(
                actor_type="admin",
                actor_ref=claims.sub,
                action="mtproto_rotated",
                target_type="mtproto_secret",
                target_id=str(fresh.id),
                payload={
                    "cloak_domain": cloak,
                    "revoked_secret_id": revoked_id,
                },
            )
        )

    full = _full_secret(new_hex, cloak)
    return RotateOut(
        secret_id=str(fresh.id),
        secret_hex=new_hex,
        cloak_domain=cloak,
        full_secret=full,
        config_line=f'secret = "{full}"',
        host=settings.mtg_host,
        port=settings.mtg_port,
        rotated_at=fresh.created_at,
        revoked_secret_id=revoked_id,
    )
