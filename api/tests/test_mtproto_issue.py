"""Integration tests for ``POST /internal/mtproto/issue`` (Stage 8 + Stage 9).

Skipped unless ``VLESSICH_INTEGRATION_DB`` is exported (real Postgres
required: production schema uses ARRAY/JSONB columns incompatible with
sqlite-in-memory).

Covers:
  1. ``scope='user'`` with feature OFF → 501 ``per_user_disabled``.
  2. ``scope='shared'`` happy-path → returns ``tg://proxy?...`` deeplink
     bound to the seeded ACTIVE shared secret.
  3. No active subscription → 403 ``no_active_subscription``.
  4. ``scope='user'`` with feature ON + pre-seeded FREE pool → 200,
     port from pool, row flipped to ACTIVE (Stage 9).
  5. ``scope='user'`` with feature ON + empty pool → 503 ``pool_full``.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")

import pytest

if "VLESSICH_INTEGRATION_DB" not in os.environ:
    pytest.skip("integration DB not configured", allow_module_level=True)

import orjson
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import get_sessionmaker
from app.main import app
from app.models import MtprotoSecret, Subscription, User

SECRET = b"x" * 32


def _sign(method: str, path: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    msg = f"{method}\n{path}\n{ts}\n".encode() + body
    sig = hmac.new(SECRET, msg, hashlib.sha256).hexdigest()
    return {
        "x-vlessich-ts": ts,
        "x-vlessich-sig": sig,
        "content-type": "application/json",
    }


async def _seed_user_with_sub(tg_id: int) -> None:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        s.add(User(tg_id=tg_id, phone_e164=f"+7999000{tg_id:04d}"))
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


async def _ensure_shared_secret() -> None:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        existing = await s.scalar(
            select(MtprotoSecret).where(
                MtprotoSecret.scope == "shared",
                MtprotoSecret.status == "ACTIVE",
            )
        )
        if existing is not None:
            return
        s.add(
            MtprotoSecret(
                secret_hex="ab" * 16,
                cloak_domain="www.microsoft.com",
                scope="shared",
                status="ACTIVE",
            )
        )


async def _wipe_user_pool() -> None:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        await s.execute(delete(MtprotoSecret).where(MtprotoSecret.scope == "user"))


async def _seed_free_slot(port: int, secret_hex: str) -> str:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        row = MtprotoSecret(
            secret_hex=secret_hex,
            cloak_domain="www.microsoft.com",
            scope="user",
            status="FREE",
            user_id=None,
            port=port,
        )
        s.add(row)
        await s.flush()
        return str(row.id)


def _enable_per_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_MTG_PER_USER_ENABLED", "true")
    get_settings.cache_clear()


def _disable_per_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_MTG_PER_USER_ENABLED", "false")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_user_scope_returns_501_when_feature_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_per_user(monkeypatch)
    tg_id = 50_000_000 + (uuid.uuid4().int % 1_000_000)
    await _seed_user_with_sub(tg_id)
    await _ensure_shared_secret()

    body = orjson.dumps({"tg_id": tg_id, "scope": "user"})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            "/internal/mtproto/issue",
            content=body,
            headers=_sign("POST", "/internal/mtproto/issue", body),
        )
    assert r.status_code == 501, r.text
    assert r.json()["code"] == "per_user_disabled"


@pytest.mark.asyncio
async def test_shared_scope_returns_deeplink() -> None:
    tg_id = 51_000_000 + (uuid.uuid4().int % 1_000_000)
    await _seed_user_with_sub(tg_id)
    await _ensure_shared_secret()

    body = orjson.dumps({"tg_id": tg_id, "scope": "shared"})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            "/internal/mtproto/issue",
            content=body,
            headers=_sign("POST", "/internal/mtproto/issue", body),
        )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["tg_deeplink"].startswith("tg://proxy?server=")
    assert "&secret=ee" in payload["tg_deeplink"]
    assert isinstance(payload["host"], str) and payload["host"]
    assert isinstance(payload["port"], int) and payload["port"] > 0


@pytest.mark.asyncio
async def test_no_subscription_returns_403() -> None:
    tg_id = 52_000_000 + (uuid.uuid4().int % 1_000_000)
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        s.add(User(tg_id=tg_id, phone_e164=f"+7999111{tg_id % 10000:04d}"))
    await _ensure_shared_secret()

    body = orjson.dumps({"tg_id": tg_id, "scope": "shared"})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            "/internal/mtproto/issue",
            content=body,
            headers=_sign("POST", "/internal/mtproto/issue", body),
        )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "no_active_subscription"

    # Cleanup the orphan user so re-runs stay deterministic.
    async with sm() as s, s.begin():
        await s.execute(delete(User).where(User.tg_id == tg_id))


@pytest.mark.asyncio
async def test_user_scope_allocates_from_free_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_per_user(monkeypatch)
    try:
        await _wipe_user_pool()
        tg_id = 53_000_000 + (uuid.uuid4().int % 1_000_000)
        await _seed_user_with_sub(tg_id)
        port = 18_443
        slot_id = await _seed_free_slot(port, "cd" * 16)

        body = orjson.dumps({"tg_id": tg_id, "scope": "user"})
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as ac:
            r = await ac.post(
                "/internal/mtproto/issue",
                content=body,
                headers=_sign("POST", "/internal/mtproto/issue", body),
            )
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["port"] == port
        assert "&secret=eecd" in payload["tg_deeplink"]

        sm = get_sessionmaker()
        async with sm() as s:
            row = await s.scalar(
                select(MtprotoSecret).where(MtprotoSecret.id == uuid.UUID(slot_id))
            )
            assert row is not None
            assert row.status == "ACTIVE"
            assert row.user_id == tg_id
            assert row.port == port
    finally:
        _disable_per_user(monkeypatch)
        await _wipe_user_pool()


@pytest.mark.asyncio
async def test_user_scope_returns_503_when_pool_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_per_user(monkeypatch)
    try:
        await _wipe_user_pool()
        tg_id = 54_000_000 + (uuid.uuid4().int % 1_000_000)
        await _seed_user_with_sub(tg_id)

        body = orjson.dumps({"tg_id": tg_id, "scope": "user"})
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as ac:
            r = await ac.post(
                "/internal/mtproto/issue",
                content=body,
                headers=_sign("POST", "/internal/mtproto/issue", body),
            )
        assert r.status_code == 503, r.text
        assert r.json()["code"] == "pool_full"
    finally:
        _disable_per_user(monkeypatch)
