"""Unit tests for the active prober worker (Stage 5).

Integration tests (real Postgres) because production models depend on
Postgres-only types. Skipped unless ``VLESSICH_INTEGRATION_DB`` is set.

Asserts:

* MAINTENANCE nodes are skipped (no probe row, backend not called).
* ``probe_burn_threshold`` consecutive failures flip HEALTHY → BURNED
  + emit ``AuditLog(action='node_burned')``.
* ``probe_recover_threshold`` consecutive successes flip BURNED →
  HEALTHY + emit ``AuditLog(action='node_recovered')``.
* Intermittent failures (counter resets on OK) do not burn.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")

import pytest

if "VLESSICH_INTEGRATION_DB" not in os.environ:
    pytest.skip("integration DB not configured", allow_module_level=True)

from sqlalchemy import select

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import AuditLog, Node, NodeHealthProbe
from app.workers.probe_backends import ProbeResult
from app.workers.prober import Prober


@dataclass
class _ScriptedBackend:
    script: dict[str, list[ProbeResult]]
    calls: dict[str, int]

    @classmethod
    def make(cls, script: dict[str, list[ProbeResult]]) -> "_ScriptedBackend":
        return cls(script=script, calls={k: 0 for k in script})

    async def probe(self, hostname: str, port: int) -> ProbeResult:
        idx = self.calls[hostname]
        self.calls[hostname] = idx + 1
        seq = self.script[hostname]
        return seq[idx] if idx < len(seq) else seq[-1]


async def _seed_node(hostname: str, status: str) -> Node:
    sm = get_sessionmaker()
    async with sm() as session:
        async with session.begin():
            node = Node(hostname=hostname, status=status)
            session.add(node)
            await session.flush()
            session.expunge(node)
        return node


async def _audit_actions_for(node_id) -> list[str]:
    sm = get_sessionmaker()
    async with sm() as session:
        rows = (
            await session.execute(
                select(AuditLog).where(AuditLog.target_id == str(node_id))
            )
        ).scalars().all()
        return [r.action for r in rows]


async def _probe_count(node_id) -> int:
    sm = get_sessionmaker()
    async with sm() as session:
        rows = (
            await session.execute(
                select(NodeHealthProbe).where(NodeHealthProbe.node_id == node_id)
            )
        ).scalars().all()
        return len(rows)


@pytest.mark.asyncio
async def test_maintenance_node_is_skipped() -> None:
    host = f"maint-{uuid.uuid4().hex[:8]}.example.com"
    node = await _seed_node(host, "MAINTENANCE")
    backend = _ScriptedBackend.make({host: [ProbeResult(False, None, "boom")]})
    prober = Prober(get_sessionmaker(), [("edge", backend)], get_settings())
    written = await prober.run_once()
    assert written == 0
    assert backend.calls[host] == 0
    assert await _probe_count(node.id) == 0


@pytest.mark.asyncio
async def test_burn_after_threshold_failures() -> None:
    settings = get_settings()
    host = f"burn-{uuid.uuid4().hex[:8]}.example.com"
    node = await _seed_node(host, "HEALTHY")
    backend = _ScriptedBackend.make({host: [ProbeResult(False, None, "timeout")]})
    prober = Prober(get_sessionmaker(), [("edge", backend)], settings)
    for _ in range(settings.probe_burn_threshold):
        await prober.run_once()

    sm = get_sessionmaker()
    async with sm() as session:
        refreshed = await session.scalar(select(Node).where(Node.id == node.id))
    assert refreshed is not None
    assert refreshed.status == "BURNED"
    assert "node_burned" in await _audit_actions_for(node.id)
    assert await _probe_count(node.id) == settings.probe_burn_threshold


@pytest.mark.asyncio
async def test_recover_after_threshold_successes() -> None:
    settings = get_settings()
    host = f"rec-{uuid.uuid4().hex[:8]}.example.com"
    node = await _seed_node(host, "BURNED")
    backend = _ScriptedBackend.make({host: [ProbeResult(True, 12, None)]})
    prober = Prober(get_sessionmaker(), [("edge", backend)], settings)
    for _ in range(settings.probe_recover_threshold):
        await prober.run_once()

    sm = get_sessionmaker()
    async with sm() as session:
        refreshed = await session.scalar(select(Node).where(Node.id == node.id))
    assert refreshed is not None
    assert refreshed.status == "HEALTHY"
    actions = await _audit_actions_for(node.id)
    assert "node_recovered" in actions


@pytest.mark.asyncio
async def test_intermittent_failures_do_not_burn() -> None:
    settings = get_settings()
    host = f"flap-{uuid.uuid4().hex[:8]}.example.com"
    node = await _seed_node(host, "HEALTHY")
    seq = [
        ProbeResult(False, None, "x"),
        ProbeResult(True, 10, None),
        ProbeResult(False, None, "x"),
        ProbeResult(True, 10, None),
        ProbeResult(False, None, "x"),
    ]
    backend = _ScriptedBackend.make({host: seq})
    prober = Prober(get_sessionmaker(), [("edge", backend)], settings)
    for _ in range(len(seq)):
        await prober.run_once()

    sm = get_sessionmaker()
    async with sm() as session:
        refreshed = await session.scalar(select(Node).where(Node.id == node.id))
    assert refreshed is not None
    assert refreshed.status == "HEALTHY"
    assert "node_burned" not in await _audit_actions_for(node.id)
