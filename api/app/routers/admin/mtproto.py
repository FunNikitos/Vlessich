"""Admin MTProto rotation + per-user pool management (Stage 8 + Stage 9).

Stage 8:
* ``POST /admin/mtproto/rotate`` — superadmin-only shared secret rotation.

Stage 9 (FREE-pool model):
* ``POST /admin/mtproto/pool/bootstrap`` — superadmin. Idempotent.
  Inserts FREE-status rows for a contiguous port range. Returns the
  full secret material (one-time) so the operator can render
  ``mtg/config.toml`` for the per-user mtg containers and deploy
  them via Ansible. Ports already present in the DB (FREE/ACTIVE/
  REVOKED) are skipped.
* ``GET  /admin/mtproto/pool/config`` — superadmin. Dumps all
  non-REVOKED per-user rows (FREE + ACTIVE) so the operator can
  rebuild mtg config from the source-of-truth. Includes full secret
  material — do NOT cache the response.
* ``POST /admin/mtproto/users/{uid}/rotate`` — superadmin. Marks the
  user's current ACTIVE secret REVOKED and claims a fresh FREE slot.
  Consumes a pool slot (port stays bound to the REVOKED row until
  operator rebuilds mtg config).
* ``POST /admin/mtproto/users/{uid}/revoke`` — superadmin. Marks the
  user's ACTIVE secret REVOKED without allocating a replacement.
* ``GET  /admin/mtproto/users`` — readonly+. Paginated list of
  per-user secrets (metadata only, no secret material).

Audit trail: ``mtproto_rotated`` / ``mtproto_pool_bootstrapped`` /
``mtproto_pool_config_dumped`` / ``mtproto_user_rotated`` /
``mtproto_user_revoked`` — payload never carries secret_hex.
"""
from __future__ import annotations

import secrets as pysecrets
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import AdminClaims, require_admin_role
from app.config import get_settings
from app.db import get_redis, get_session
from app.errors import ApiCode, api_error
from app.models import AuditLog, MtprotoSecret
from app.services.mtproto_allocator import (
    free_pool_count,
    full_secret,
    revoke_user_secret,
    rotate_user_secret,
)
from app.services.mtproto_broadcast import emit_rotation_event

router = APIRouter(prefix="/admin/mtproto", tags=["admin"])

_READ_ROLES = ("superadmin", "support", "readonly")


# ---------------------------------------------------------------------------
# Shared rotation (Stage 8)
# ---------------------------------------------------------------------------
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


@router.post(
    "/rotate",
    response_model=RotateOut,
    status_code=status.HTTP_200_OK,
)
async def rotate(
    payload: RotateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
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

    full = full_secret(new_hex, cloak)
    if settings.mtg_broadcast_enabled:
        try:
            await emit_rotation_event(
                redis, scope="shared", secret_id=str(fresh.id)
            )
        except Exception:  # noqa: BLE001 — broadcast best-effort
            pass
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


# ---------------------------------------------------------------------------
# Pool bootstrap + config dump (Stage 9)
# ---------------------------------------------------------------------------
class PoolBootstrapIn(BaseModel):
    count: int | None = Field(
        default=None,
        ge=1,
        le=512,
        description="Number of FREE slots to ensure exist. Defaults to mtg_per_user_pool_size.",
    )
    port_base: int | None = Field(
        default=None,
        ge=1,
        le=65535,
        description="First port of the range. Defaults to mtg_per_user_port_base.",
    )
    cloak_domain: str | None = Field(
        default=None,
        min_length=4,
        max_length=255,
        description="Cloak domain bound to newly-inserted FREE rows. Defaults to mtg_shared_cloak.",
    )


class PoolSlotOut(BaseModel):
    secret_id: str
    port: int
    secret_hex: str
    cloak_domain: str
    full_secret: str


class PoolBootstrapOut(BaseModel):
    inserted_ports: list[int]
    skipped_ports: list[int]
    items: list[PoolSlotOut] = Field(
        ...,
        description="Full secret material for newly-inserted FREE slots. Shown ONCE.",
    )
    host: str


@router.post(
    "/pool/bootstrap",
    response_model=PoolBootstrapOut,
    status_code=status.HTTP_200_OK,
)
async def bootstrap_pool(
    payload: PoolBootstrapIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    claims: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> PoolBootstrapOut:
    settings = get_settings()
    count = payload.count if payload.count is not None else settings.mtg_per_user_pool_size
    port_base = (
        payload.port_base if payload.port_base is not None else settings.mtg_per_user_port_base
    )
    cloak = (payload.cloak_domain or settings.mtg_shared_cloak).strip()
    if not cloak:
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            ApiCode.INVALID_REQUEST,
            "cloak_domain пуст.",
        )
    if port_base + count - 1 > 65535:
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            ApiCode.INVALID_REQUEST,
            "port_base + count выходит за 65535.",
        )

    wanted = list(range(port_base, port_base + count))
    inserted: list[tuple[MtprotoSecret, str]] = []
    skipped: list[int] = []

    async with session.begin():
        existing_ports_rows = await session.execute(
            select(MtprotoSecret.port).where(
                MtprotoSecret.scope == "user",
                MtprotoSecret.port.in_(wanted),
            )
        )
        existing_ports = {p for (p,) in existing_ports_rows.all() if p is not None}

        for port in wanted:
            if port in existing_ports:
                skipped.append(port)
                continue
            new_hex = pysecrets.token_hex(16)
            row = MtprotoSecret(
                secret_hex=new_hex,
                cloak_domain=cloak,
                scope="user",
                status="FREE",
                user_id=None,
                port=port,
            )
            session.add(row)
            inserted.append((row, new_hex))

        await session.flush()

        session.add(
            AuditLog(
                actor_type="admin",
                actor_ref=claims.sub,
                action="mtproto_pool_bootstrapped",
                target_type="mtproto_pool",
                target_id=None,
                payload={
                    "count": count,
                    "port_base": port_base,
                    "cloak_domain": cloak,
                    "inserted_ports": [row.port for row, _ in inserted],
                    "skipped_ports": skipped,
                },
            )
        )

    items = [
        PoolSlotOut(
            secret_id=str(row.id),
            port=row.port or 0,
            secret_hex=hex_,
            cloak_domain=row.cloak_domain,
            full_secret=full_secret(hex_, row.cloak_domain),
        )
        for row, hex_ in inserted
    ]
    return PoolBootstrapOut(
        inserted_ports=[row.port or 0 for row, _ in inserted],
        skipped_ports=skipped,
        items=items,
        host=settings.mtg_host,
    )


class PoolConfigSlotOut(BaseModel):
    secret_id: str
    port: int
    status: str
    user_id: int | None
    secret_hex: str
    cloak_domain: str
    full_secret: str


class PoolConfigOut(BaseModel):
    host: str
    items: list[PoolConfigSlotOut]


@router.get("/pool/config", response_model=PoolConfigOut)
async def dump_pool_config(
    session: Annotated[AsyncSession, Depends(get_session)],
    claims: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> PoolConfigOut:
    settings = get_settings()
    async with session.begin():
        rows = (
            (
                await session.execute(
                    select(MtprotoSecret)
                    .where(
                        MtprotoSecret.scope == "user",
                        MtprotoSecret.status.in_(("FREE", "ACTIVE")),
                    )
                    .order_by(MtprotoSecret.port.asc())
                )
            )
            .scalars()
            .all()
        )
        session.add(
            AuditLog(
                actor_type="admin",
                actor_ref=claims.sub,
                action="mtproto_pool_config_dumped",
                target_type="mtproto_pool",
                target_id=None,
                payload={"count": len(rows)},
            )
        )

    items = [
        PoolConfigSlotOut(
            secret_id=str(r.id),
            port=r.port or 0,
            status=r.status,
            user_id=r.user_id,
            secret_hex=r.secret_hex,
            cloak_domain=r.cloak_domain,
            full_secret=full_secret(r.secret_hex, r.cloak_domain),
        )
        for r in rows
    ]
    return PoolConfigOut(host=settings.mtg_host, items=items)


# ---------------------------------------------------------------------------
# Per-user rotate / revoke / list (Stage 9)
# ---------------------------------------------------------------------------
class UserRotateOut(BaseModel):
    secret_id: str
    user_id: int
    port: int
    cloak_domain: str
    rotated_at: datetime
    revoked_secret_id: str | None
    pool_free_remaining: int


@router.post("/users/{uid}/rotate", response_model=UserRotateOut)
async def rotate_user(
    uid: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    claims: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> UserRotateOut:
    settings = get_settings()
    if not settings.mtg_per_user_enabled:
        raise api_error(
            status.HTTP_501_NOT_IMPLEMENTED,
            ApiCode.PER_USER_DISABLED,
            "Персональный MTProto выключен.",
        )

    async with session.begin():
        new_secret, revoked_id = await rotate_user_secret(session, uid)
        remaining = await free_pool_count(session)
        session.add(
            AuditLog(
                actor_type="admin",
                actor_ref=claims.sub,
                action="mtproto_user_rotated",
                target_type="mtproto_secret",
                target_id=str(new_secret.id),
                payload={
                    "user_id": uid,
                    "port": new_secret.port,
                    "revoked_secret_id": revoked_id,
                },
            )
        )

    assert new_secret.port is not None
    if settings.mtg_broadcast_enabled:
        try:
            await emit_rotation_event(
                redis,
                scope="user",
                secret_id=str(new_secret.id),
                user_id=uid,
            )
        except Exception:  # noqa: BLE001 — broadcast best-effort
            pass
    return UserRotateOut(
        secret_id=str(new_secret.id),
        user_id=uid,
        port=new_secret.port,
        cloak_domain=new_secret.cloak_domain,
        rotated_at=new_secret.created_at,
        revoked_secret_id=revoked_id,
        pool_free_remaining=remaining,
    )


class UserRevokeOut(BaseModel):
    secret_id: str
    user_id: int
    revoked: bool


@router.post("/users/{uid}/revoke", response_model=UserRevokeOut)
async def revoke_user(
    uid: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    claims: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> UserRevokeOut:
    async with session.begin():
        revoked = await revoke_user_secret(session, uid)
        if revoked is None:
            raise api_error(
                status.HTTP_404_NOT_FOUND,
                ApiCode.USER_NOT_FOUND,
                "У пользователя нет активного персонального MTProto.",
            )
        session.add(
            AuditLog(
                actor_type="admin",
                actor_ref=claims.sub,
                action="mtproto_user_revoked",
                target_type="mtproto_secret",
                target_id=str(revoked.id),
                payload={"user_id": uid, "port": revoked.port},
            )
        )

    return UserRevokeOut(secret_id=str(revoked.id), user_id=uid, revoked=True)


class UserSecretOut(BaseModel):
    secret_id: UUID
    user_id: int | None
    port: int
    status: str
    cloak_domain: str
    created_at: datetime


class UserSecretListOut(BaseModel):
    total: int
    items: list[UserSecretOut]


@router.get("/users", response_model=UserSecretListOut)
async def list_user_secrets(
    session: Annotated[AsyncSession, Depends(get_session)],
    _claims: Annotated[AdminClaims, Depends(require_admin_role(*_READ_ROLES))],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    user_id: int | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> UserSecretListOut:
    if status_filter is not None and status_filter not in ("FREE", "ACTIVE", "REVOKED"):
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            ApiCode.INVALID_REQUEST,
            "status must be FREE|ACTIVE|REVOKED",
        )

    stmt = (
        select(MtprotoSecret)
        .where(MtprotoSecret.scope == "user")
        .order_by(MtprotoSecret.port.asc())
    )
    if status_filter is not None:
        stmt = stmt.where(MtprotoSecret.status == status_filter)
    if user_id is not None:
        stmt = stmt.where(MtprotoSecret.user_id == user_id)

    total = int(
        await session.scalar(
            select(func.count()).select_from(stmt.subquery())
        )
        or 0
    )
    rows = (
        (await session.execute(stmt.offset((page - 1) * limit).limit(limit)))
        .scalars()
        .all()
    )
    items = [
        UserSecretOut(
            secret_id=r.id,
            user_id=r.user_id,
            port=r.port or 0,
            status=r.status,
            cloak_domain=r.cloak_domain,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return UserSecretListOut(total=total, items=items)
