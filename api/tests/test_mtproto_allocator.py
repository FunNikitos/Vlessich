"""Unit/integration tests for ``app.services.mtproto_allocator`` (Stage 9).

Skipped unless ``VLESSICH_INTEGRATION_DB`` is exported — the FREE-pool
allocator relies on Postgres-specific ``SELECT … FOR UPDATE SKIP
LOCKED`` semantics and CHECK constraints that don't exist in sqlite.

Covers:
  1. Empty pool → ``POOL_FULL`` HTTPException on allocate.
  2. FREE → ACTIVE flip claims the lowest-port slot.
  3. Idempotent: calling allocate twice for the same user returns the
     same row, pool not consumed.
  4. ``rotate_user_secret`` REVOKEs current ACTIVE and claims a fresh
     FREE slot (port stays bound on the REVOKED row).
  5. ``revoke_user_secret`` transitions ACTIVE→REVOKED, returns row;
     returns ``None`` if no ACTIVE exists.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")

import pytest

if "VLESSICH_INTEGRATION_DB" not in os.environ:
    pytest.skip("integration DB not configured", allow_module_level=True)

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.db import get_sessionmaker
from app.models import MtprotoSecret, Subscription, User
from app.services.mtproto_allocator import (
    allocate_user_secret,
    free_pool_count,
    get_active_user_secret,
    revoke_user_secret,
    rotate_user_secret,
)


async def _wipe_user_pool() -> None:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        await s.execute(delete(MtprotoSecret).where(MtprotoSecret.scope == "user"))


async def _seed_user_with_sub(tg_id: int) -> None:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        s.add(User(tg_id=tg_id, phone_e164=f"+7999777{tg_id % 10000:04d}"))
        await s.flush()
        s.add(
            Subscription(
                user_id=tg_id,
                status="ACTIVE",
                plan_name="month",
                started_at=datetime.now(UTC) - timedelta(days=1),
                expires_at=datetime.now(UTC) + timedelta(days=29),
                devices_limit=3,
            )
        )


async def _seed_free_slots(ports: list[int]) -> None:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        for i, port in enumerate(ports):
            s.add(
                MtprotoSecret(
                    secret_hex=f"{i:02d}" * 16,
                    cloak_domain="www.microsoft.com",
                    scope="user",
                    status="FREE",
                    user_id=None,
                    port=port,
                )
            )


@pytest.mark.asyncio
async def test_allocate_raises_pool_full_when_empty() -> None:
    await _wipe_user_pool()
    tg_id = 60_000_000 + (uuid.uuid4().int % 1_000_000)
    await _seed_user_with_sub(tg_id)

    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        with pytest.raises(HTTPException) as excinfo:
            await allocate_user_secret(s, tg_id)
    assert excinfo.value.status_code == 503
    detail = excinfo.value.detail
    assert isinstance(detail, dict) and detail.get("code") == "pool_full"


@pytest.mark.asyncio
async def test_allocate_claims_lowest_port_free_slot() -> None:
    await _wipe_user_pool()
    tg_id = 61_000_000 + (uuid.uuid4().int % 1_000_000)
    await _seed_user_with_sub(tg_id)
    await _seed_free_slots([18_600, 18_601, 18_602])

    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        claimed = await allocate_user_secret(s, tg_id)
    assert claimed.status == "ACTIVE"
    assert claimed.user_id == tg_id
    assert claimed.port == 18_600

    async with sm() as s:
        remaining = await free_pool_count(s)
    assert remaining == 2


@pytest.mark.asyncio
async def test_allocate_is_idempotent_for_existing_active() -> None:
    await _wipe_user_pool()
    tg_id = 62_000_000 + (uuid.uuid4().int % 1_000_000)
    await _seed_user_with_sub(tg_id)
    await _seed_free_slots([18_700, 18_701])

    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        first = await allocate_user_secret(s, tg_id)
    async with sm() as s, s.begin():
        second = await allocate_user_secret(s, tg_id)
    assert first.id == second.id
    async with sm() as s:
        remaining = await free_pool_count(s)
    # Only one FREE slot consumed.
    assert remaining == 1


@pytest.mark.asyncio
async def test_rotate_revokes_current_and_claims_fresh_slot() -> None:
    await _wipe_user_pool()
    tg_id = 63_000_000 + (uuid.uuid4().int % 1_000_000)
    await _seed_user_with_sub(tg_id)
    await _seed_free_slots([18_800, 18_801])

    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        first = await allocate_user_secret(s, tg_id)
    async with sm() as s, s.begin():
        rotated, revoked_id = await rotate_user_secret(s, tg_id)

    assert revoked_id == str(first.id)
    assert rotated.id != first.id
    assert rotated.status == "ACTIVE"
    assert rotated.port == 18_801

    async with sm() as s:
        old = await s.scalar(
            select(MtprotoSecret).where(MtprotoSecret.id == first.id)
        )
        assert old is not None
        assert old.status == "REVOKED"
        # Port stays bound on the REVOKED row — mtg still serves that
        # secret until the operator rebuilds config.
        assert old.port == 18_800


@pytest.mark.asyncio
async def test_revoke_returns_none_when_no_active() -> None:
    await _wipe_user_pool()
    tg_id = 64_000_000 + (uuid.uuid4().int % 1_000_000)
    await _seed_user_with_sub(tg_id)

    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        result = await revoke_user_secret(s, tg_id)
    assert result is None


@pytest.mark.asyncio
async def test_revoke_transitions_active_to_revoked() -> None:
    await _wipe_user_pool()
    tg_id = 65_000_000 + (uuid.uuid4().int % 1_000_000)
    await _seed_user_with_sub(tg_id)
    await _seed_free_slots([18_900])

    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        active = await allocate_user_secret(s, tg_id)
    async with sm() as s, s.begin():
        revoked = await revoke_user_secret(s, tg_id)
    assert revoked is not None
    assert revoked.id == active.id
    assert revoked.status == "REVOKED"

    async with sm() as s:
        current = await get_active_user_secret(s, tg_id)
    assert current is None
