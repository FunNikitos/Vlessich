"""Integration tests for ``POST /admin/mtproto/rotate`` (Stage 8 T4).

Skipped unless ``VLESSICH_INTEGRATION_DB`` is exported.

Covers:
  1. superadmin rotate happy-path: previous ACTIVE shared → REVOKED,
     new ACTIVE shared inserted, AuditLog ``mtproto_rotated`` emitted,
     response carries ``ee`` + 32hex + hex(cloak) full secret.
  2. support role → 403 ``forbidden``.
  3. ``cloak_domain`` payload override is reflected in response and DB.
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

from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.auth.admin import Role, create_access_token
from app.db import get_sessionmaker
from app.main import app
from app.models import AuditLog, MtprotoSecret


def _bearer(role: str) -> dict[str, str]:
    token = create_access_token("integ-mtg-admin", cast(Role, role))
    return {"Authorization": f"Bearer {token}"}


async def _wipe_shared() -> None:
    sm = get_sessionmaker()
    async with sm() as s, s.begin():
        await s.execute(
            delete(MtprotoSecret).where(MtprotoSecret.scope == "shared")
        )


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
