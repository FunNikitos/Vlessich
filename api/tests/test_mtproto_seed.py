"""Idempotency tests for ``app.startup.mtproto_seed.seed_shared_secret``.

Skipped unless ``VLESSICH_INTEGRATION_DB`` is exported.

Covers:
  1. Empty pool + valid env → inserts exactly one row, returns True.
  2. Second invocation → no-op, returns False (idempotent).
  3. Env unset → no-op, returns False.
  4. Invalid hex → no-op, returns False (does not raise).
"""
from __future__ import annotations

import os

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")

import pytest

if "VLESSICH_INTEGRATION_DB" not in os.environ:
    pytest.skip("integration DB not configured", allow_module_level=True)

from pydantic import SecretStr
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import MtprotoSecret
from app.startup.mtproto_seed import seed_shared_secret


async def _wipe_shared() -> None:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        await s.execute(
            delete(MtprotoSecret).where(MtprotoSecret.scope == "shared")
        )


@pytest.mark.asyncio
async def test_seed_inserts_when_empty_then_idempotent() -> None:
    await _wipe_shared()
    settings = get_settings().model_copy(
        update={
            "mtg_shared_secret_hex": SecretStr("ab" * 16),
            "mtg_shared_cloak": "www.microsoft.com",
        }
    )
    sm = get_sessionmaker()

    inserted_first = await seed_shared_secret(sm, settings)
    assert inserted_first is True

    async with sm() as s:
        rows = (
            await s.execute(
                select(MtprotoSecret).where(
                    MtprotoSecret.scope == "shared",
                    MtprotoSecret.status == "ACTIVE",
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].secret_hex == "ab" * 16

    inserted_second = await seed_shared_secret(sm, settings)
    assert inserted_second is False

    async with sm() as s:
        rows = (
            await s.execute(
                select(MtprotoSecret).where(
                    MtprotoSecret.scope == "shared",
                    MtprotoSecret.status == "ACTIVE",
                )
            )
        ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_seed_skips_without_env() -> None:
    await _wipe_shared()
    settings = get_settings().model_copy(
        update={"mtg_shared_secret_hex": None}
    )
    sm = get_sessionmaker()
    inserted = await seed_shared_secret(sm, settings)
    assert inserted is False

    async with sm() as s:
        rows = (
            await s.execute(
                select(MtprotoSecret).where(MtprotoSecret.scope == "shared")
            )
        ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_seed_rejects_invalid_hex() -> None:
    await _wipe_shared()
    settings = get_settings().model_copy(
        update={"mtg_shared_secret_hex": SecretStr("not-hex-value")}
    )
    sm = get_sessionmaker()
    inserted = await seed_shared_secret(sm, settings)
    assert inserted is False

    async with sm() as s:
        rows = (
            await s.execute(
                select(MtprotoSecret).where(MtprotoSecret.scope == "shared")
            )
        ).scalars().all()
    assert rows == []
