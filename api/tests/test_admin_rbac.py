"""Tests for admin RBAC dependency factory (Stage 2 T5)."""
from __future__ import annotations

import os

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")
os.environ.setdefault(
    "API_DATABASE_URL", "postgresql+asyncpg://vlessich:vlessich@localhost:5432/vlessich"
)

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.admin import AdminClaims, create_access_token, require_admin_role


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/admin/super-only")
    async def super_only(
        claims: AdminClaims = Depends(require_admin_role("superadmin")),
    ) -> dict[str, str]:
        return {"sub": claims.sub}

    @app.get("/admin/support-or-super")
    async def support_or_super(
        claims: AdminClaims = Depends(require_admin_role("superadmin", "support")),
    ) -> dict[str, str]:
        return {"role": claims.role}

    @app.get("/admin/anyone")
    async def anyone(
        claims: AdminClaims = Depends(
            require_admin_role("superadmin", "support", "readonly")
        ),
    ) -> dict[str, str]:
        return {"role": claims.role}

    return app


def _bearer(role: str) -> dict[str, str]:
    token = create_access_token("admin-1", role)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_super_only_allows_superadmin() -> None:
    transport = ASGITransport(app=_make_app())
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/admin/super-only", headers=_bearer("superadmin"))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_super_only_rejects_support() -> None:
    transport = ASGITransport(app=_make_app())
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/admin/super-only", headers=_bearer("support"))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_anyone_allows_readonly() -> None:
    transport = ASGITransport(app=_make_app())
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/admin/anyone", headers=_bearer("readonly"))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_missing_authorization_rejected() -> None:
    transport = ASGITransport(app=_make_app())
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/admin/anyone")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_malformed_bearer_rejected() -> None:
    transport = ASGITransport(app=_make_app())
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/admin/anyone", headers={"Authorization": "Token abc"})
    assert r.status_code == 401
