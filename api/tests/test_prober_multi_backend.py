"""Integration tests for Stage 7 multi-backend prober.

Postgres-backed (``VLESSICH_INTEGRATION_DB`` gate, same as
``test_prober.py``). Asserts that with edge+ru backends:

* each ``run_once`` writes N_nodes * N_backends probe rows,
* ``probe_source`` column is populated correctly per row,
* RU failures do NOT flip ``nodes.status`` to ``BURNED``,
* edge failures still BURN (state machine intact).
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
from app.models import Node, NodeHealthProbe
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


async def _probes(node_id) -> list[NodeHealthProbe]:
    sm = get_sessionmaker()
    async with sm() as session:
        return (
            await session.execute(
                select(NodeHealthProbe)
                .where(NodeHealthProbe.node_id == node_id)
                .order_by(NodeHealthProbe.probed_at)
            )
        ).scalars().all()


@pytest.mark.asyncio
async def test_dual_backend_records_both_sources() -> None:
    settings = get_settings()
    host = f"dual-{uuid.uuid4().hex[:8]}.example.com"
    node = await _seed_node(host, "HEALTHY")
    edge = _ScriptedBackend.make({host: [ProbeResult(True, 10, None)]})
    ru = _ScriptedBackend.make({host: [ProbeResult(True, 50, None)]})
    prober = Prober(
        get_sessionmaker(),
        [("edge", edge), ("ru", ru)],
        settings,
    )
    written = await prober.run_once()
    assert written == 2  # 1 node × 2 backends
    rows = await _probes(node.id)
    sources = {row.probe_source for row in rows}
    assert sources == {"edge", "ru"}


@pytest.mark.asyncio
async def test_ru_failures_do_not_burn_node() -> None:
    settings = get_settings()
    host = f"ruonly-{uuid.uuid4().hex[:8]}.example.com"
    node = await _seed_node(host, "HEALTHY")
    edge = _ScriptedBackend.make({host: [ProbeResult(True, 10, None)]})
    ru = _ScriptedBackend.make({host: [ProbeResult(False, None, "blocked")]})
    prober = Prober(
        get_sessionmaker(),
        [("edge", edge), ("ru", ru)],
        settings,
    )
    # Run far past the burn threshold: edge is always OK, RU always fails.
    for _ in range(settings.probe_burn_threshold + 2):
        await prober.run_once()

    sm = get_sessionmaker()
    async with sm() as session:
        refreshed = await session.scalar(select(Node).where(Node.id == node.id))
    assert refreshed is not None
    assert refreshed.status == "HEALTHY", "RU failures must not burn"


@pytest.mark.asyncio
async def test_edge_failures_still_burn_when_ru_ok() -> None:
    settings = get_settings()
    host = f"edgefail-{uuid.uuid4().hex[:8]}.example.com"
    node = await _seed_node(host, "HEALTHY")
    edge = _ScriptedBackend.make({host: [ProbeResult(False, None, "timeout")]})
    ru = _ScriptedBackend.make({host: [ProbeResult(True, 10, None)]})
    prober = Prober(
        get_sessionmaker(),
        [("edge", edge), ("ru", ru)],
        settings,
    )
    for _ in range(settings.probe_burn_threshold):
        await prober.run_once()

    sm = get_sessionmaker()
    async with sm() as session:
        refreshed = await session.scalar(select(Node).where(Node.id == node.id))
    assert refreshed is not None
    assert refreshed.status == "BURNED"
