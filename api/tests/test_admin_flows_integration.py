"""Admin codes integration flow (Stage 2 T9).

Requires a real Postgres (creates schema from metadata, no alembic) and a
Redis instance. Skipped unless ``VLESSICH_INTEGRATION_DB`` is exported.
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

from httpx import ASGITransport, AsyncClient

from app.auth.admin import create_access_token
from app.main import app


def _bearer(role: str) -> dict[str, str]:
    token = create_access_token("integ-admin", role)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_admin_codes_full_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        # Superadmin creates 3 codes.
        r = await ac.post(
            "/admin/codes",
            headers=_bearer("superadmin"),
            json={
                "plan_name": "3m",
                "duration_days": 90,
                "devices_limit": 3,
                "count": 3,
                "allowed_locations": ["fi"],
            },
        )
        assert r.status_code == 201, r.text
        created = r.json()
        assert created["created"] == 3
        assert len(created["codes"]) == 3

        # Readonly can list.
        r = await ac.get("/admin/codes", headers=_bearer("readonly"))
        assert r.status_code == 200
        assert r.json()["total"] >= 3

        # Support can create, cannot revoke.
        r = await ac.post(
            "/admin/codes",
            headers=_bearer("support"),
            json={
                "plan_name": "1m",
                "duration_days": 30,
                "devices_limit": 1,
                "count": 1,
                "allowed_locations": ["fi"],
            },
        )
        assert r.status_code == 201

        # Fetch one code id for deletion.
        r = await ac.get("/admin/codes?limit=1", headers=_bearer("superadmin"))
        assert r.status_code == 200
        code_id = r.json()["items"][0]["id"]

        # Support forbidden from DELETE.
        r = await ac.delete(f"/admin/codes/{code_id}", headers=_bearer("support"))
        assert r.status_code == 403

        # Superadmin deletes.
        r = await ac.delete(f"/admin/codes/{code_id}", headers=_bearer("superadmin"))
        assert r.status_code == 204


@pytest.mark.asyncio
async def test_admin_nodes_flow() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            "/admin/nodes",
            headers=_bearer("superadmin"),
            json={
                "hostname": "test-node-01.example.com",
                "current_ip": "1.2.3.4",
                "region": "fi",
                "status": "HEALTHY",
            },
        )
        assert r.status_code == 201
        node = r.json()

        r = await ac.patch(
            f"/admin/nodes/{node['id']}",
            headers=_bearer("superadmin"),
            json={"status": "MAINTENANCE"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "MAINTENANCE"

        # Support cannot create.
        r = await ac.post(
            "/admin/nodes",
            headers=_bearer("support"),
            json={
                "hostname": "x.example.com",
                "current_ip": "1.2.3.5",
                "region": "fi",
            },
        )
        assert r.status_code == 403
