"""Admin stats + subscription revoke + node health integration tests (Stage 4 T1).

Requires a real Postgres (creates schema from metadata, no alembic) and a
Redis instance. Skipped unless ``VLESSICH_INTEGRATION_DB`` is exported.
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

from typing import cast

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select  # noqa: F401  (kept for future use)

from app.auth.admin import Role, create_access_token
from app.db import get_sessionmaker
from app.main import app
from app.models import Node, NodeHealthProbe, Subscription, User


def _bearer(role: str) -> dict[str, str]:
    token = create_access_token("integ-admin", cast(Role, role))
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_admin_stats_counts_entities() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/admin/stats", headers=_bearer("readonly"))
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "users_total",
        "codes_total",
        "codes_unused",
        "subs_active",
        "subs_trial",
        "nodes_total",
        "nodes_healthy",
        "nodes_burned",
        "nodes_maintenance",
        "nodes_stale",
    ):
        assert key in body
        assert isinstance(body[key], int)


@pytest.mark.asyncio
async def test_admin_stats_rejects_missing_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get("/admin/stats")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_subscription_revoke_transitions_and_audits() -> None:
    sm = get_sessionmaker()
    tg_id = 8_000_000_001
    sub_id = uuid.uuid4()
    async with sm() as session:
        async with session.begin():
            session.add(User(tg_id=tg_id, tg_username="t", lang="ru"))
            session.add(
                Subscription(
                    id=sub_id,
                    user_id=tg_id,
                    plan="1m",
                    started_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                    devices_limit=1,
                    adblock=True,
                    smart_routing=True,
                    status="ACTIVE",
                    sub_url_token=f"tok_{sub_id.hex[:12]}",
                )
            )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        # readonly forbidden
        r = await ac.post(
            f"/admin/subscriptions/{sub_id}/revoke",
            headers=_bearer("readonly"),
        )
        assert r.status_code == 403

        # support allowed
        r = await ac.post(
            f"/admin/subscriptions/{sub_id}/revoke",
            headers=_bearer("support"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "REVOKED"

        # second call → 409
        r = await ac.post(
            f"/admin/subscriptions/{sub_id}/revoke",
            headers=_bearer("support"),
        )
        assert r.status_code == 409
        assert r.json()["code"] == "already_inactive"

        # missing → 404
        r = await ac.post(
            f"/admin/subscriptions/{uuid.uuid4()}/revoke",
            headers=_bearer("support"),
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_node_health_aggregates_recent_probes() -> None:
    sm = get_sessionmaker()
    node_id = uuid.uuid4()
    async with sm() as session:
        async with session.begin():
            session.add(
                Node(
                    id=node_id,
                    hostname=f"n-{node_id.hex[:8]}.test",
                    current_ip="10.0.0.1",
                    region="fi",
                    status="HEALTHY",
                )
            )
            now = datetime.now(UTC)
            for i in range(10):
                session.add(
                    NodeHealthProbe(
                        node_id=node_id,
                        probed_at=now - timedelta(minutes=i),
                        ok=(i % 3 != 0),
                        latency_ms=20 + i,
                    )
                )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(
            f"/admin/nodes/{node_id}/health",
            headers=_bearer("readonly"),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hostname"].startswith("n-")
    assert body["status"] == "HEALTHY"
    assert len(body["recent_probes"]) == 10
    assert body["uptime_24h_pct"] is not None
    assert 0.0 <= body["uptime_24h_pct"] <= 100.0
    assert body["latency_p50_ms"] is not None


@pytest.mark.asyncio
async def test_node_health_404_for_missing() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        r = await ac.get(
            f"/admin/nodes/{uuid.uuid4()}/health",
            headers=_bearer("readonly"),
        )
    assert r.status_code == 404
    assert r.json()["code"] == "node_not_found"
