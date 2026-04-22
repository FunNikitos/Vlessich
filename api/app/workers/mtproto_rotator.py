"""Cron-driven MTProto shared-secret auto-rotation (Stage 10).

Runs as a separate container (``docker-compose.dev.yml::mtproto_rotator``).
Every ``mtg_rotator_interval_sec`` seconds it:

1. SELECTs the currently-ACTIVE shared MTProto secret.
2. If its ``created_at`` is older than ``mtg_shared_rotation_days`` AND
   ``mtg_auto_rotation_enabled`` is True — runs the same rotation
   procedure as ``POST /admin/mtproto/rotate`` with
   ``actor_type='system'`` and emits a ``mtproto:rotated`` event for
   the broadcaster (only when ``mtg_broadcast_enabled``).
3. Updates the ``vlessich_mtproto_shared_secret_age_seconds`` gauge so
   the ``MtprotoSharedSecretStale`` alert fires if rotator is wedged.

The worker is intentionally skinny: rotation logic lives inline (we
duplicate the SQL from the admin route rather than refactoring the
router right now — Stage 10 keeps surface change minimal). All
operator-visible behaviour is identical to the manual endpoint:
ACTIVE → REVOKED, fresh row → ACTIVE, audit `mtproto_auto_rotated`.
"""
from __future__ import annotations

import asyncio
import secrets as pysecrets
from datetime import UTC, datetime
from typing import Final

import structlog
from prometheus_client import start_http_server
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import close_engine, get_sessionmaker, init_engine
from app.logging import setup_logging
from app.metrics import (
    MTPROTO_AUTO_ROTATION_TOTAL,
    MTPROTO_SHARED_SECRET_AGE_SECONDS,
)
from app.models import AuditLog, MtprotoSecret
from app.services.mtproto_broadcast import emit_rotation_event

log = structlog.get_logger("mtproto.rotator")

METRICS_PORT: Final = 9102


async def _load_active_shared(session: AsyncSession) -> MtprotoSecret | None:
    return await session.scalar(
        select(MtprotoSecret).where(
            MtprotoSecret.scope == "shared",
            MtprotoSecret.status == "ACTIVE",
        )
    )


async def _rotate_shared_in_tx(
    session: AsyncSession, *, cloak: str
) -> tuple[MtprotoSecret, str | None]:
    """Mirror of ``admin.mtproto.rotate`` body (system actor).

    Caller MUST own the outer transaction. Returns ``(fresh, revoked_id)``.
    """
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

    new_hex = pysecrets.token_hex(16)
    fresh = MtprotoSecret(
        secret_hex=new_hex,
        cloak_domain=cloak,
        scope="shared",
        status="ACTIVE",
    )
    session.add(fresh)
    await session.flush()
    return fresh, revoked_id


async def run_once(
    settings: Settings,
    redis: Redis | None,
    *,
    now: datetime | None = None,
) -> str:
    """One scan pass. Returns one of ``rotated|skipped|disabled|error``.

    ``redis`` may be None when broadcast is disabled — rotation still
    proceeds, broadcast emit is skipped.
    """
    sm = get_sessionmaker()
    when = now or datetime.now(UTC)

    async with sm() as session:
        async with session.begin():
            current = await _load_active_shared(session)
            if current is None:
                MTPROTO_SHARED_SECRET_AGE_SECONDS.set(0.0)
                log.info("mtproto.rotator.no_active_shared")
                return "skipped"

            age_sec = (when - current.created_at).total_seconds()
            MTPROTO_SHARED_SECRET_AGE_SECONDS.set(age_sec)

            if not settings.mtg_auto_rotation_enabled:
                log.debug("mtproto.rotator.disabled", age_sec=age_sec)
                return "disabled"

            threshold_sec = settings.mtg_shared_rotation_days * 86400
            if age_sec < threshold_sec:
                log.debug(
                    "mtproto.rotator.too_young",
                    age_sec=age_sec,
                    threshold_sec=threshold_sec,
                )
                return "skipped"

            cloak = settings.mtg_shared_cloak.strip()
            fresh, revoked_id = await _rotate_shared_in_tx(session, cloak=cloak)
            session.add(
                AuditLog(
                    actor_type="system",
                    actor_ref="mtproto_rotator",
                    action="mtproto_auto_rotated",
                    target_type="mtproto_secret",
                    target_id=str(fresh.id),
                    payload={
                        "cloak_domain": cloak,
                        "revoked_secret_id": revoked_id,
                        "age_sec": int(age_sec),
                    },
                )
            )
            new_secret_id = str(fresh.id)

    # After commit: emit broadcast event (best-effort).
    if settings.mtg_broadcast_enabled and redis is not None:
        try:
            await emit_rotation_event(
                redis, scope="shared", secret_id=new_secret_id
            )
        except Exception:  # noqa: BLE001 — never let broadcast failure mask rotation
            log.exception("mtproto.rotator.emit_failed", secret_id=new_secret_id)

    MTPROTO_AUTO_ROTATION_TOTAL.labels(result="rotated").inc()
    MTPROTO_SHARED_SECRET_AGE_SECONDS.set(0.0)
    log.info(
        "mtproto.rotator.rotated",
        new_secret_id=new_secret_id,
        revoked_secret_id=revoked_id,
    )
    return "rotated"


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    start_http_server(METRICS_PORT)
    redis: Redis | None = None
    if settings.mtg_broadcast_enabled:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
    log.info(
        "mtproto.rotator.start",
        interval_sec=settings.mtg_rotator_interval_sec,
        enabled=settings.mtg_auto_rotation_enabled,
        broadcast=settings.mtg_broadcast_enabled,
    )
    try:
        while True:
            try:
                await run_once(settings, redis)
            except Exception:  # noqa: BLE001 — worker must survive any per-tick error
                MTPROTO_AUTO_ROTATION_TOTAL.labels(result="error").inc()
                log.exception("mtproto.rotator.tick_failed")
            await asyncio.sleep(settings.mtg_rotator_interval_sec)
    finally:
        if redis is not None:
            await redis.aclose()
        await close_engine()
        log.info("mtproto.rotator.stop")


if __name__ == "__main__":
    asyncio.run(main())
