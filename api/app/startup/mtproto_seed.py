"""Startup-time bootstrap for the MTProto shared pool (Stage 8).

Idempotent: if at least one ``MtprotoSecret(scope='shared',
status='ACTIVE')`` exists, do nothing. Otherwise — and only if
``API_MTG_SHARED_SECRET_HEX`` is set — insert a single seed row using
``API_MTG_SHARED_CLOAK`` as the cloak domain.

Why startup and not Alembic: the seed value is an environment secret,
not data, so it must not live in the migration tree. Doing it in the
lifespan keeps dev / test deployments self-bootstrapping while
staying a no-op in production where the pool is already populated.
"""
from __future__ import annotations

import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.config import Settings
from app.models import MtprotoSecret

log = structlog.get_logger("mtproto.seed")

_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


async def seed_shared_secret(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> bool:
    """Seed one shared secret if pool is empty and env is configured.

    Returns True iff a row was inserted.
    """
    if settings.mtg_shared_secret_hex is None:
        log.info("mtproto.seed.skip", reason="no_env")
        return False

    secret_value = settings.mtg_shared_secret_hex.get_secret_value().strip().lower()
    if not _HEX_RE.fullmatch(secret_value):
        log.warning(
            "mtproto.seed.skip",
            reason="invalid_hex",
            hint="MTG_SHARED_SECRET_HEX must be 32 lowercase hex chars",
        )
        return False

    async with sessionmaker() as session:
        async with session.begin():
            existing = await session.scalar(
                select(MtprotoSecret).where(
                    MtprotoSecret.scope == "shared",
                    MtprotoSecret.status == "ACTIVE",
                )
            )
            if existing is not None:
                log.info("mtproto.seed.skip", reason="already_present")
                return False
            session.add(
                MtprotoSecret(
                    secret_hex=secret_value,
                    cloak_domain=settings.mtg_shared_cloak,
                    scope="shared",
                    status="ACTIVE",
                )
            )
        log.info(
            "mtproto.seed.inserted",
            cloak=settings.mtg_shared_cloak,
        )
    return True
