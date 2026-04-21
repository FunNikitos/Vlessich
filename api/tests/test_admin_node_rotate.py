"""Integration test for ``POST /admin/nodes/{id}/rotate`` (Stage 5 T4).

Skipped unless ``VLESSICH_INTEGRATION_DB`` is exported (real Postgres
required because the production schema uses ARRAY/JSONB columns
incompatible with sqlite-in-memory).
"""
from __future__ import annotations

import os
import uuid

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")

import pytest

if "VLESSICH_INTEGRATION_DB" not in os.environ:
    pytest.skip("integration DB not configured", allow_module_level=True)

from typing import cast

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.admin import Role, create_access_token
from app.db import get_sessionmaker
from app.main import app
from app.models import AuditLog, Node


def _bearer(role: str) -> dict[str, str]:
    token = create_access_token("integ-admin", cast(Role, role))
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_rotate_resets_ip_and_status() -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        async with s.begin():
            node = Node(
                hostname=f"int-{uuid.uuid4().hex[:8]}.example.com",
                current_ip="1.2.3.4",
                status="BURNED",
            )
            s.add(node)
            await s.flush()
            node_id = node.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        # Support cannot rotate.
        r403 = await ac.post(
            f"/admin/nodes/{node_id}/rotate", headers=_bearer("support")
        )
        assert r403.status_code == 403, r403.text

        r = await ac.post(
            f"/admin/nodes/{node_id}/rotate", headers=_bearer("superadmin")
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "HEALTHY"
    assert body["current_ip"] is None

    async with sm() as s:
        refreshed = await s.scalar(select(Node).where(Node.id == node_id))
        assert refreshed is not None
        assert refreshed.status == "HEALTHY"
        assert refreshed.current_ip is None
        audit = (
            await s.execute(
                select(AuditLog).where(
                    AuditLog.action == "node_rotated",
                    AuditLog.target_id == str(node_id),
                )
            )
        ).scalars().all()
        assert len(audit) == 1
        assert audit[0].payload is not None
        assert audit[0].payload.get("previous_ip") == "1.2.3.4"
        assert audit[0].payload.get("previous_status") == "BURNED"


@pytest.mark.asyncio
async def test_rotate_404_for_unknown_node() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.post(
            f"/admin/nodes/{uuid.uuid4()}/rotate", headers=_bearer("superadmin")
        )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "node_not_found"
