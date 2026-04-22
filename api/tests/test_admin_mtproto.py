"""Integration tests for ``/admin/mtproto/*`` (Stage 8 + Stage 9 T6).

Skipped unless ``VLESSICH_INTEGRATION_DB`` is exported.

Stage 8 (shared rotation):
  1. superadmin rotate happy-path: previous ACTIVE shared → REVOKED,
     new ACTIVE shared inserted, AuditLog ``mtproto_rotated`` emitted,
     response carries ``ee`` + 32hex + hex(cloak) full secret.
  2. support role → 403 ``forbidden``.
  3. ``cloak_domain`` payload override is reflected in response and DB.

Stage 9 (per-user pool):
  4. /pool/bootstrap idempotent: second call reports ``skipped_ports``
     for the already-present range, no duplicates inserted; audit
     payload carries ``inserted_ports``/``skipped_ports`` only.
  5. /pool/config dump exposes FREE+ACTIVE rows, omits REVOKED.
  6. /users/{uid}/rotate (feature on): REVOKE current ACTIVE +
     allocate fresh FREE, audit ``mtproto_user_rotated`` carries
     ``port`` + ``revoked_secret_id`` (no secret material).
  7. /users/{uid}/revoke: ACTIVE→REVOKED + audit; 404 when no ACTIVE.
  8. RBAC: support → 403 on /users/{uid}/rotate; readonly → 403 on
     /pool/bootstrap; readonly → 200 on GET /users.
"""
from __future__ import annotations

import os
from typing import cast

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")

import pytest

if "VLESSICH_INTEGRATION_DB" not in os.environ:
    pytest.skip("integration DB not configured", allow_module_level=True)

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.auth.admin import Role, create_access_token
from app.config import get_settings
from app.db import get_sessionmaker
from app.main import app
from app.models import AuditLog, MtprotoSecret, Subscription, User


def _bearer(role: str) -> dict[str, str]:
    token = create_access_token("integ-mtg-admin", cast(Role, role))
    return {"Authorization": f"Bearer {token}"}


async def _wipe_shared() -> None:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        await s.execute(
            delete(MtprotoSecret).where(MtprotoSecret.scope == "shared")
        )


async def _wipe_user_pool() -> None:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        await s.execute(delete(MtprotoSecret).where(MtprotoSecret.scope == "user"))


async def _seed_active_shared(secret_hex: str, cloak: str) -> str:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        row = MtprotoSecret(
            secret_hex=secret_hex,
            cloak_domain=cloak,
            scope="shared",
            status="ACTIVE",
        )
        s.add(row)
        await s.flush()
        return str(row.id)


async def _seed_user_with_sub(tg_id: int) -> None:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        s.add(User(tg_id=tg_id, phone_e164=f"+7999888{tg_id % 10000:04d}"))
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


# ---------------------------------------------------------------------------
# Stage 8: shared rotation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rotate_revokes_previous_and_inserts_new() -> None:
    await _wipe_shared()
    old_hex = "cd" * 16
    old_id = await _seed_active_shared(old_hex, "www.microsoft.com")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            "/admin/mtproto/rotate", json={}, headers=_bearer("superadmin")
        )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["revoked_secret_id"] == old_id
    assert body["secret_id"] != old_id
    assert len(body["secret_hex"]) == 32
    assert body["secret_hex"] != old_hex
    assert body["full_secret"].startswith("ee" + body["secret_hex"])
    assert body["full_secret"].endswith(body["cloak_domain"].encode().hex())
    assert body["config_line"] == f'secret = "{body["full_secret"]}"'

    sm = get_sessionmaker()
    async with sm() as s:
        active = (
            await s.execute(
                select(MtprotoSecret).where(
                    MtprotoSecret.scope == "shared",
                    MtprotoSecret.status == "ACTIVE",
                )
            )
        ).scalars().all()
        assert len(active) == 1
        assert str(active[0].id) == body["secret_id"]

        old = await s.scalar(
            select(MtprotoSecret).where(MtprotoSecret.id == UUID(old_id))
        )
        assert old is not None
        assert old.status == "REVOKED"

        audits = (
            await s.execute(
                select(AuditLog).where(
                    AuditLog.action == "mtproto_rotated",
                    AuditLog.target_id == body["secret_id"],
                )
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].payload is not None
        assert audits[0].payload.get("revoked_secret_id") == old_id
        # Secret material must NEVER appear in audit payload.
        assert "secret_hex" not in audits[0].payload
        assert "full_secret" not in audits[0].payload


@pytest.mark.asyncio
async def test_rotate_forbidden_for_support_role() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            "/admin/mtproto/rotate", json={}, headers=_bearer("support")
        )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_rotate_with_cloak_override() -> None:
    await _wipe_shared()
    await _seed_active_shared("ef" * 16, "www.microsoft.com")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            "/admin/mtproto/rotate",
            json={"cloak_domain": "www.cloudflare.com"},
            headers=_bearer("superadmin"),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cloak_domain"] == "www.cloudflare.com"
    assert body["full_secret"].endswith("www.cloudflare.com".encode().hex())


# ---------------------------------------------------------------------------
# Stage 9: pool bootstrap + config dump
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pool_bootstrap_is_idempotent() -> None:
    await _wipe_user_pool()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r1 = await ac.post(
            "/admin/mtproto/pool/bootstrap",
            json={"count": 3, "port_base": 19_000},
            headers=_bearer("superadmin"),
        )
        assert r1.status_code == 200, r1.text
        b1 = r1.json()
        assert b1["inserted_ports"] == [19_000, 19_001, 19_002]
        assert b1["skipped_ports"] == []
        assert len(b1["items"]) == 3
        for item in b1["items"]:
            assert item["full_secret"].startswith("ee" + item["secret_hex"])

        r2 = await ac.post(
            "/admin/mtproto/pool/bootstrap",
            json={"count": 3, "port_base": 19_000},
            headers=_bearer("superadmin"),
        )
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["inserted_ports"] == []
    assert b2["skipped_ports"] == [19_000, 19_001, 19_002]
    assert b2["items"] == []

    sm = get_sessionmaker()
    async with sm() as s:
        rows = (
            await s.execute(
                select(MtprotoSecret).where(MtprotoSecret.scope == "user")
            )
        ).scalars().all()
        assert len(rows) == 3
        ports = sorted(r.port for r in rows if r.port is not None)
        assert ports == [19_000, 19_001, 19_002]
        assert all(r.status == "FREE" for r in rows)

        audits = (
            await s.execute(
                select(AuditLog).where(
                    AuditLog.action == "mtproto_pool_bootstrapped"
                )
            )
        ).scalars().all()
        # At least the two calls above; payloads must NOT carry secret hex.
        assert len(audits) >= 2
        for a in audits:
            assert a.payload is not None
            assert "secret_hex" not in a.payload
            assert "items" not in a.payload


@pytest.mark.asyncio
async def test_pool_bootstrap_forbidden_for_readonly() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            "/admin/mtproto/pool/bootstrap",
            json={"count": 1, "port_base": 21_000},
            headers=_bearer("readonly"),
        )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_pool_config_dump_exposes_free_and_active() -> None:
    await _wipe_user_pool()
    await _seed_free_slot(19_500, "11" * 16)
    tg_id = 70_000_000 + (uuid.uuid4().int % 1_000_000)
    await _seed_user_with_sub(tg_id)
    # Mark second slot ACTIVE for this user.
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        active = MtprotoSecret(
            secret_hex="22" * 16,
            cloak_domain="www.microsoft.com",
            scope="user",
            status="ACTIVE",
            user_id=tg_id,
            port=19_501,
        )
        s.add(active)
        revoked = MtprotoSecret(
            secret_hex="33" * 16,
            cloak_domain="www.microsoft.com",
            scope="user",
            status="REVOKED",
            user_id=tg_id,
            port=19_502,
        )
        s.add(revoked)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(
            "/admin/mtproto/pool/config", headers=_bearer("superadmin")
        )
    assert r.status_code == 200, r.text
    body = r.json()
    statuses = sorted(item["status"] for item in body["items"])
    assert statuses == ["ACTIVE", "FREE"]
    assert all(
        item["full_secret"].startswith("ee" + item["secret_hex"])
        for item in body["items"]
    )


# ---------------------------------------------------------------------------
# Stage 9: per-user rotate / revoke / list
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_user_rotate_revokes_and_claims_fresh_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_per_user(monkeypatch)
    try:
        await _wipe_user_pool()
        tg_id = 71_000_000 + (uuid.uuid4().int % 1_000_000)
        await _seed_user_with_sub(tg_id)
        first_id = await _seed_free_slot(20_000, "44" * 16)
        await _seed_free_slot(20_001, "55" * 16)
        # Manually claim first slot for the user to simulate prior allocation.
        sm = get_sessionmaker()
        async with sm() as s, s.begin():
            row = await s.scalar(
                select(MtprotoSecret).where(MtprotoSecret.id == UUID(first_id))
            )
            assert row is not None
            row.status = "ACTIVE"
            row.user_id = tg_id

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as ac:
            r = await ac.post(
                f"/admin/mtproto/users/{tg_id}/rotate",
                headers=_bearer("superadmin"),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["revoked_secret_id"] == first_id
        assert body["port"] == 20_001
        assert body["pool_free_remaining"] == 0

        async with sm() as s:
            old = await s.scalar(
                select(MtprotoSecret).where(MtprotoSecret.id == UUID(first_id))
            )
            assert old is not None
            assert old.status == "REVOKED"

            audits = (
                await s.execute(
                    select(AuditLog).where(
                        AuditLog.action == "mtproto_user_rotated",
                        AuditLog.target_id == body["secret_id"],
                    )
                )
            ).scalars().all()
            assert len(audits) == 1
            assert audits[0].payload is not None
            assert audits[0].payload.get("port") == 20_001
            assert audits[0].payload.get("user_id") == tg_id
            assert "secret_hex" not in audits[0].payload
    finally:
        _disable_per_user(monkeypatch)


@pytest.mark.asyncio
async def test_user_rotate_forbidden_for_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_per_user(monkeypatch)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as ac:
            r = await ac.post(
                "/admin/mtproto/users/12345/rotate",
                headers=_bearer("support"),
            )
        assert r.status_code == 403, r.text
    finally:
        _disable_per_user(monkeypatch)


@pytest.mark.asyncio
async def test_user_revoke_returns_404_when_no_active() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            "/admin/mtproto/users/99999999/revoke",
            headers=_bearer("superadmin"),
        )
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "user_not_found"


@pytest.mark.asyncio
async def test_user_revoke_marks_active_revoked() -> None:
    await _wipe_user_pool()
    tg_id = 72_000_000 + (uuid.uuid4().int % 1_000_000)
    await _seed_user_with_sub(tg_id)
    slot_id = await _seed_free_slot(20_500, "66" * 16)
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        row = await s.scalar(
            select(MtprotoSecret).where(MtprotoSecret.id == UUID(slot_id))
        )
        assert row is not None
        row.status = "ACTIVE"
        row.user_id = tg_id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            f"/admin/mtproto/users/{tg_id}/revoke",
            headers=_bearer("superadmin"),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["secret_id"] == slot_id
    assert body["revoked"] is True

    async with sm() as s:
        row = await s.scalar(
            select(MtprotoSecret).where(MtprotoSecret.id == UUID(slot_id))
        )
        assert row is not None
        assert row.status == "REVOKED"


@pytest.mark.asyncio
async def test_list_user_secrets_readonly_can_view() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(
            "/admin/mtproto/users",
            params={"limit": 10},
            headers=_bearer("readonly"),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body and "items" in body
    for item in body["items"]:
        # Metadata only — no secret material.
        assert "secret_hex" not in item
        assert "full_secret" not in item
