"""Active node prober (Stage 5).

Runs as a separate container (``docker-compose.dev.yml::prober``). Every
``probe_interval_sec`` seconds it opens a TCP connection to every
non-MAINTENANCE node on ``probe_port`` with ``probe_timeout_sec``,
records a ``NodeHealthProbe`` row, updates ``nodes.last_probe_at`` on
success/failure, and applies BURN / RECOVER state transitions:

* ``probe_burn_threshold`` consecutive failures → ``status = BURNED`` +
  ``AuditLog(action="node_burned")``.
* ``probe_recover_threshold`` consecutive successes after BURNED →
  ``status = HEALTHY`` + ``AuditLog(action="node_recovered")``.

MAINTENANCE nodes are skipped (admin owns lifecycle).

The probe backend is a ``Protocol`` so tests can inject a fake without a
network. The default backend uses ``asyncio.open_connection``.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Final, Protocol
from uuid import UUID

import structlog
from prometheus_client import start_http_server
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import close_engine, get_sessionmaker, init_engine
from app.logging import setup_logging
from app.models import AuditLog, Node, NodeHealthProbe
from app.workers.prober_metrics import (
    NODE_BURNED_TOTAL,
    NODE_RECOVERED_TOTAL,
    PROBE_DURATION_SECONDS,
    PROBE_TOTAL,
    set_node_state,
)

log = structlog.get_logger("prober")

_MAX_ERROR_LEN: Final = 256


@dataclass(slots=True, frozen=True)
class ProbeResult:
    ok: bool
    latency_ms: int | None
    error: str | None


class ProbeBackend(Protocol):
    async def probe(self, hostname: str, port: int) -> ProbeResult: ...


class TcpProbeBackend:
    """TCP-connect probe (default).

    Successful connect within timeout → ``ok=True`` with measured latency.
    Any exception (timeout, refused, DNS) → ``ok=False`` with the
    exception's repr (truncated).
    """

    def __init__(self, timeout_sec: float) -> None:
        self._timeout = timeout_sec

    async def probe(self, hostname: str, port: int) -> ProbeResult:
        started = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(hostname, port),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            return ProbeResult(ok=False, latency_ms=None, error="timeout")
        except OSError as exc:
            msg = str(exc) or exc.__class__.__name__
            return ProbeResult(
                ok=False, latency_ms=None, error=msg[:_MAX_ERROR_LEN]
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            # Best-effort close; we still recorded a successful connect.
            pass
        return ProbeResult(ok=True, latency_ms=latency_ms, error=None)


@dataclass(slots=True)
class _Counters:
    """In-memory consecutive ok/fail counters per node (reset each tick run)."""

    fails: int = 0
    oks: int = 0


class Prober:
    """Stateful prober: keeps per-node consecutive counters across ticks."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        backend: ProbeBackend,
        settings: Settings,
    ) -> None:
        self._sm = sessionmaker
        self._backend = backend
        self._settings = settings
        self._counters: dict[UUID, _Counters] = defaultdict(_Counters)

    async def run_once(self) -> int:
        """One probe pass. Returns number of probes recorded."""
        async with self._sm() as session:
            nodes = (
                await session.execute(
                    select(Node).where(Node.status != "MAINTENANCE")
                )
            ).scalars().all()

        if not nodes:
            return 0

        results = await asyncio.gather(
            *(self._backend.probe(n.hostname, self._settings.probe_port) for n in nodes),
            return_exceptions=False,
        )

        async with self._sm() as session:
            async with session.begin():
                for node, result in zip(nodes, results, strict=True):
                    await self._apply(session, node, result)
        return len(nodes)

    async def _apply(
        self, session: AsyncSession, node: Node, result: ProbeResult
    ) -> None:
        # Metrics: every probe contributes to total + duration histogram.
        ok_label = "true" if result.ok else "false"
        PROBE_TOTAL.labels(ok=ok_label).inc()
        if result.latency_ms is not None:
            PROBE_DURATION_SECONDS.labels(ok=ok_label).observe(
                result.latency_ms / 1000.0
            )

        # Record probe row (always, append-only log).
        session.add(
            NodeHealthProbe(
                node_id=node.id,
                ok=result.ok,
                latency_ms=result.latency_ms,
                error=result.error,
            )
        )
        # Update last_probe_at on the node row.
        node.last_probe_at = func.now()

        counters = self._counters[node.id]
        if result.ok:
            counters.oks += 1
            counters.fails = 0
        else:
            counters.fails += 1
            counters.oks = 0

        log.info(
            "prober.probe",
            node_id=str(node.id),
            hostname=node.hostname,
            ok=result.ok,
            latency_ms=result.latency_ms,
            error=result.error,
            consecutive_fails=counters.fails,
            consecutive_oks=counters.oks,
        )

        # State transitions.
        if (
            node.status == "HEALTHY"
            and counters.fails >= self._settings.probe_burn_threshold
        ):
            node.status = "BURNED"
            session.add(
                AuditLog(
                    actor_type="system",
                    actor_ref="prober",
                    action="node_burned",
                    target_type="node",
                    target_id=str(node.id),
                    payload={
                        "hostname": node.hostname,
                        "consecutive_fails": counters.fails,
                        "last_error": result.error,
                    },
                )
            )
            log.warning(
                "prober.node_burned",
                node_id=str(node.id),
                hostname=node.hostname,
                consecutive_fails=counters.fails,
            )
            counters.fails = 0
            NODE_BURNED_TOTAL.inc()
        elif (
            node.status == "BURNED"
            and counters.oks >= self._settings.probe_recover_threshold
        ):
            node.status = "HEALTHY"
            session.add(
                AuditLog(
                    actor_type="system",
                    actor_ref="prober",
                    action="node_recovered",
                    target_type="node",
                    target_id=str(node.id),
                    payload={
                        "hostname": node.hostname,
                        "consecutive_oks": counters.oks,
                    },
                )
            )
            log.info(
                "prober.node_recovered",
                node_id=str(node.id),
                hostname=node.hostname,
                consecutive_oks=counters.oks,
            )
            counters.oks = 0
            NODE_RECOVERED_TOTAL.inc()

        # Publish current state gauge (one-hot).
        set_node_state(str(node.id), node.hostname, node.status)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    sm = get_sessionmaker()
    backend = TcpProbeBackend(timeout_sec=settings.probe_timeout_sec)
    prober = Prober(sm, backend, settings)
    # Expose Prometheus /metrics on a dedicated port (separate from API).
    start_http_server(settings.probe_metrics_port)
    log.info(
        "prober.start",
        interval_sec=settings.probe_interval_sec,
        timeout_sec=settings.probe_timeout_sec,
        port=settings.probe_port,
        burn_threshold=settings.probe_burn_threshold,
        recover_threshold=settings.probe_recover_threshold,
        metrics_port=settings.probe_metrics_port,
    )
    try:
        while True:
            try:
                await prober.run_once()
            except Exception:  # noqa: BLE001 — worker must survive any per-tick error
                log.exception("prober.tick_failed")
            await asyncio.sleep(settings.probe_interval_sec)
    finally:
        await close_engine()
        log.info("prober.stop")


if __name__ == "__main__":
    asyncio.run(main())
