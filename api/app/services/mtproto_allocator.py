"""Per-user MTProto secret allocator (Stage 9, FREE-pool model).

Source-of-truth = DB. The pool is pre-seeded by an admin via
``POST /admin/mtproto/pool/bootstrap`` with one row per port (status
``FREE``). The allocator only *claims* a FREE row for a user — it
never mints new secret material at runtime, because mtg only
forwards traffic for secrets statically configured in
``mtg/config.toml``.

Concurrency: ``SELECT … FOR UPDATE SKIP LOCKED LIMIT 1`` so
parallel issue calls grab distinct rows. Caller MUST hold an outer
transaction (``async with session.begin()``).

Idempotency: if the user already has an ACTIVE per-user secret,
return it as-is.

Pool exhaustion: raises ``api_error(503, POOL_FULL)``.
"""
from __future__ import annotations

import structlog
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiCode, api_error
from app.models import MtprotoSecret

log = structlog.get_logger("mtproto.allocator")


async def get_active_user_secret(
    session: AsyncSession, user_id: int
) -> MtprotoSecret | None:
    """Return the user's ACTIVE per-user secret, if any (no locking)."""
    return await session.scalar(
        select(MtprotoSecret).where(
            MtprotoSecret.scope == "user",
            MtprotoSecret.user_id == user_id,
            MtprotoSecret.status == "ACTIVE",
        )
    )


async def free_pool_count(session: AsyncSession) -> int:
    """Count FREE per-user slots (no locking)."""
    from sqlalchemy import func

    return int(
        await session.scalar(
            select(func.count())
            .select_from(MtprotoSecret)
            .where(
                MtprotoSecret.scope == "user",
                MtprotoSecret.status == "FREE",
            )
        )
        or 0
    )


async def _claim_free_slot(
    session: AsyncSession, user_id: int
) -> MtprotoSecret | None:
    """Claim the lowest-port FREE slot under SKIP LOCKED. Returns None if pool empty."""
    free = await session.scalar(
        select(MtprotoSecret)
        .where(
            MtprotoSecret.scope == "user",
            MtprotoSecret.status == "FREE",
        )
        .order_by(MtprotoSecret.port.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if free is None:
        return None
    free.status = "ACTIVE"
    free.user_id = user_id
    await session.flush()
    return free


async def allocate_user_secret(
    session: AsyncSession, user_id: int
) -> MtprotoSecret:
    """Allocate or return existing ACTIVE per-user secret.

    Caller MUST hold an outer transaction.
    """
    existing = await get_active_user_secret(session, user_id)
    if existing is not None:
        return existing

    claimed = await _claim_free_slot(session, user_id)
    if claimed is None:
        log.warning("mtproto.allocator.pool_full", user_id=user_id)
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiCode.POOL_FULL,
            "MTProto перегружен, попробуй позже.",
        )

    log.info(
        "mtproto.allocator.allocated",
        user_id=user_id,
        port=claimed.port,
        secret_id=str(claimed.id),
    )
    return claimed


async def rotate_user_secret(
    session: AsyncSession, user_id: int
) -> tuple[MtprotoSecret, str | None]:
    """Revoke current ACTIVE user-secret (if any) and claim a fresh FREE slot.

    Returns ``(new_secret, revoked_secret_id_or_none)``. Caller MUST
    hold an outer transaction. Pool exhaustion → ``POOL_FULL``
    (caller's tx rolls back the REVOKE so we don't leave the user
    without a secret).
    """
    current = await session.scalar(
        select(MtprotoSecret)
        .where(
            MtprotoSecret.scope == "user",
            MtprotoSecret.user_id == user_id,
            MtprotoSecret.status == "ACTIVE",
        )
        .with_for_update()
    )
    revoked_id: str | None = None
    if current is not None:
        current.status = "REVOKED"
        revoked_id = str(current.id)
        await session.flush()

    claimed = await _claim_free_slot(session, user_id)
    if claimed is None:
        log.warning("mtproto.allocator.rotate_pool_full", user_id=user_id)
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiCode.POOL_FULL,
            "MTProto перегружен, попробуй позже.",
        )

    log.info(
        "mtproto.allocator.rotated",
        user_id=user_id,
        port=claimed.port,
        secret_id=str(claimed.id),
        revoked_secret_id=revoked_id,
    )
    return claimed, revoked_id


async def revoke_user_secret(
    session: AsyncSession, user_id: int
) -> MtprotoSecret | None:
    """Mark the user's ACTIVE per-user secret REVOKED. Returns the row, or None.

    Caller MUST hold an outer transaction. Does NOT free the port back
    to FREE — the secret is dead but mtg still serves it until the
    operator rebuilds mtg config from the pool dump.
    """
    current = await session.scalar(
        select(MtprotoSecret)
        .where(
            MtprotoSecret.scope == "user",
            MtprotoSecret.user_id == user_id,
            MtprotoSecret.status == "ACTIVE",
        )
        .with_for_update()
    )
    if current is None:
        return None
    current.status = "REVOKED"
    await session.flush()
    log.info(
        "mtproto.allocator.revoked",
        user_id=user_id,
        secret_id=str(current.id),
    )
    return current


def deeplink(host: str, port: int, secret_hex: str, cloak: str) -> str:
    """Build the canonical ``tg://proxy?...`` URL for an mtg secret.

    Layout: ``ee`` + 32 hex (random) + hex(cloak-domain).
    """
    cloak_hex = cloak.encode().hex()
    full = f"ee{secret_hex}{cloak_hex}"
    return f"tg://proxy?server={host}&port={port}&secret={full}"


def full_secret(secret_hex: str, cloak: str) -> str:
    """Raw mtg secret string (``ee`` + 32hex + hex(cloak))."""
    return f"ee{secret_hex}{cloak.encode().hex()}"
