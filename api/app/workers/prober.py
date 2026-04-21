"""Active node prober (Stage 5 + Stage 7).

Runs as a separate container (``docker-compose.dev.yml::prober``). Every
``probe_interval_sec`` seconds it probes each non-MAINTENANCE node
through every configured backend:

* ``edge`` (``TcpProbeBackend``, always on) — control-plane TCP-connect
  from the prober's own location. Drives the BURN / RECOVER state
  machine (``probe_burn_threshold`` / ``probe_recover_threshold``).
* ``ru``  (``HttpProxyProbeBackend``, enabled when ``API_RU_PROXY_URL``
  is set) — GET through a residential RU proxy. **Telemetry only** —
  never flips node status. Populates dashboards so operators can spot
  "edge OK, RU FAIL" = regional DPI / blocking.

Each probe appends one ``NodeHealthProbe`` row with ``probe_source`` in
{``edge``, ``ru``}. The admin /admin/nodes/{id}/health endpoint filters
to ``edge`` to keep historic semantics.

Backends are injected as ``list[tuple[str, ProbeBackend]]`` so tests can
swap scripted fakes.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import structlog
from prometheus_client import start_http_server
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import close_engine, get_sessionmaker, init_engine
from app.logging import setup_logging
from app.models import AuditLog, Node, NodeHealthProbe
from app.workers.probe_backends import (
    HttpProxyProbeBackend,
    ProbeResult,
    TcpProbeBackend,
)
from app.workers.prober_metrics import (
    NODE_BURNED_TOTAL,
    NODE_RECOVERED_TOTAL,
    PROBE_DURATION_SECONDS,
    PROBE_TOTAL,
    set_node_state,
)

log = structlog.get_logger("prober")

_EDGE: str = "edge"
_RU: str = "ru"


class ProbeBackend(Protocol):
    async def probe(self, hostname: str, port: int) -> ProbeResult: ...


@dataclass(slots=True)
class _Counters:
    """In-memory consecutive ok/fail counters per node (edge-only)."""

    fails: int = 0
    oks: int = 0


class Prober:
    """Stateful prober: keeps per-node consecutive counters across ticks.

    State transitions driven exclusively by the ``edge`` backend; the
    ``ru`` backend is recorded and metered but never changes
    ``nodes.status``.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        backends: list[tuple[str, ProbeBackend]],
        settings: Settings,
    ) -> None:
        if not backends:
            raise ValueError("prober requires at least one backend")
        sources = [src for src, _ in backends]
        if _EDGE not in sources:
            raise ValueError("prober requires an 'edge' backend")
        if len(set(sources)) != len(sources):
            raise ValueError("duplicate probe source names")
        self._sm = sessionmaker
        self._backends = backends
        self._settings = settings
        self._counters: dict[UUID, _Counters] = defaultdict(_Counters)

    async def run_once(self) -> int:
        """One probe pass. Returns total number of probes recorded
        (``len(nodes) * len(backends)``)."""
        async with self._sm() as session:
            nodes = (
                await session.execute(
                    select(Node).where(Node.status != "MAINTENANCE")
                )
            ).scalars().all()

        if not nodes:
            return 0

        port = self._settings.probe_port
        # Build (source, node, coroutine) triples and gather in one shot.
        tasks: list[tuple[str, Node]] = []
        coros = []
        for source, backend in self._backends:
            for node in nodes:
                tasks.append((source, node))
                coros.append(backend.probe(node.hostname, port))
        results = await asyncio.gather(*coros, return_exceptions=False)

        # Group per-node edge result so state machine + NODE_STATE gauge
        # run exactly once per node (after edge probe applied).
        async with self._sm() as session:
            async with session.begin():
                for (source, node), result in zip(tasks, results, strict=True):
                    await self._apply(session, node, source, result)
        return len(tasks)

    async def _apply(
        self,
        session: AsyncSession,
        node: Node,
        source: str,
        result: ProbeResult,
    ) -> None:
        # Metrics: every probe contributes, labelled by source.
        ok_label = "true" if result.ok else "false"
        PROBE_TOTAL.labels(ok=ok_label, source=source).inc()
        if result.latency_ms is not None:
            PROBE_DURATION_SECONDS.labels(ok=ok_label, source=source).observe(
                result.latency_ms / 1000.0
            )

        # Append-only probe row tagged by source.
        session.add(
            NodeHealthProbe(
                node_id=node.id,
                ok=result.ok,
                latency_ms=result.latency_ms,
                error=result.error,
                probe_source=source,
            )
        )

        log.info(
            "prober.probe",
            node_id=str(node.id),
            hostname=node.hostname,
            source=source,
            ok=result.ok,
            latency_ms=result.latency_ms,
            error=result.error,
        )

        if source != _EDGE:
            # RU (and any future non-edge) backends are telemetry only.
            return

        # --- Edge path: updates last_probe_at, counters, state machine ---
        node.last_probe_at = func.now()

        counters = self._counters[node.id]
        if result.ok:
            counters.oks += 1
            counters.fails = 0
        else:
            counters.fails += 1
            counters.oks = 0

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

        # Publish current state gauge (one-hot) after edge pass.
        set_node_state(str(node.id), node.hostname, node.status)


def _build_backends(settings: Settings) -> list[tuple[str, ProbeBackend]]:
    """Assemble backend list from settings.

    Always includes ``edge``. Appends ``ru`` iff ``ru_proxy_url`` is set.
    Kept as a module-level helper so tests can build the list without
    standing up the full ``main()`` wiring.
    """
    backends: list[tuple[str, ProbeBackend]] = [
        (_EDGE, TcpProbeBackend(timeout_sec=settings.probe_timeout_sec)),
    ]
    if settings.ru_proxy_url:
        backends.append(
            (
                _RU,
                HttpProxyProbeBackend(
                    proxy_url=settings.ru_proxy_url,
                    timeout_sec=settings.ru_probe_timeout_sec,
                ),
            )
        )
    return backends


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    sm = get_sessionmaker()
    backends = _build_backends(settings)
    prober = Prober(sm, backends, settings)
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
        sources=[src for src, _ in backends],
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
