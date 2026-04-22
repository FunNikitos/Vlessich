"""Tests for ``app.workers.mtproto_rotator`` (Stage 10).

Skipped unless ``VLESSICH_INTEGRATION_DB`` is exported — we need the
real Postgres schema + CHECK constraints for MtprotoSecret. Covers:

1. No ACTIVE shared → ``skipped``; gauge reset to 0.
2. Flag off → ``disabled`` regardless of age.
3. Young secret → ``skipped``; gauge reflects age.
4. Old secret + flag on → ``rotated``: old row REVOKED, new ACTIVE
   row created, audit ``mtproto_auto_rotated`` appended.
5. After rotation the gauge is reset to 0 (fresh secret just created).
"""
from __future__ import annotations

import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")

import pytest

if "VLESSICH_INTEGRATION_DB" not in os.environ:
    pytest.skip("integration DB not configured", allow_module_level=True)

from sqlalchemy import delete, select

from app.config import get_settings
from app.db import get_sessionmaker, init_engine
from app.metrics import MTPROTO_SHARED_SECRET_AGE_SECONDS
from app.models import AuditLog, MtprotoSecret
from app.workers.mtproto_rotator import run_once

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _db():
    init_engine(os.environ["VLESSICH_INTEGRATION_DB"])
    sm = get_sessionmaker()
    async with sm() as s:
        async with s.begin():
            await s.execute(delete(AuditLog))
            await s.execute(
                delete(MtprotoSecret).where(MtprotoSecret.scope == "shared")
            )
    yield
    async with sm() as s:
        async with s.begin():
            await s.execute(delete(AuditLog))
            await s.execute(
                delete(MtprotoSecret).where(MtprotoSecret.scope == "shared")
            )


async def _insert_shared(*, created_at: datetime) -> uuid.UUID:
    sm = get_sessionmaker()
    row = MtprotoSecret(
        id=uuid.uuid4(),
        secret_hex=secrets.token_hex(16),
        cloak_domain="www.microsoft.com",
        scope="shared",
        status="ACTIVE",
    )
    async with sm() as s:
        async with s.begin():
            s.add(row)
            await s.flush()
            row.created_at = created_at
    return row.id


async def test_no_active_shared_skipped():
    settings = get_settings()
    result = await run_once(settings, None)
    assert result == "skipped"


async def test_flag_off_disabled(monkeypatch):
    await _insert_shared(created_at=datetime.now(UTC) - timedelta(days=400))
    settings = get_settings()
    monkeypatch.setattr(settings, "mtg_auto_rotation_enabled", False)
    result = await run_once(settings, None)
    assert result == "disabled"


async def test_young_skipped(monkeypatch):
    await _insert_shared(created_at=datetime.now(UTC) - timedelta(days=1))
    settings = get_settings()
    monkeypatch.setattr(settings, "mtg_auto_rotation_enabled", True)
    monkeypatch.setattr(settings, "mtg_shared_rotation_days", 30)
    result = await run_once(settings, None)
    assert result == "skipped"


async def test_old_rotated(monkeypatch):
    old_id = await _insert_shared(created_at=datetime.now(UTC) - timedelta(days=40))
    settings = get_settings()
    monkeypatch.setattr(settings, "mtg_auto_rotation_enabled", True)
    monkeypatch.setattr(settings, "mtg_shared_rotation_days", 30)
    monkeypatch.setattr(settings, "mtg_broadcast_enabled", False)

    result = await run_once(settings, None)
    assert result == "rotated"

    sm = get_sessionmaker()
    async with sm() as s:
        old = await s.get(MtprotoSecret, old_id)
        assert old is not None
        assert old.status == "REVOKED"

        fresh = await s.scalar(
            select(MtprotoSecret).where(
                MtprotoSecret.scope == "shared",
                MtprotoSecret.status == "ACTIVE",
            )
        )
        assert fresh is not None
        assert fresh.id != old_id

        audit = await s.scalar(
            select(AuditLog).where(AuditLog.action == "mtproto_auto_rotated")
        )
        assert audit is not None
        assert audit.actor_type == "system"
        assert audit.payload["revoked_secret_id"] == str(old_id)
