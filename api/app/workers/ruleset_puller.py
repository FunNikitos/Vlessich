"""Background worker: periodically pull all enabled ruleset sources.

Mirrors the ``mtproto_rotator`` worker shape: a thin asyncio loop that
calls a sans-I/O ``run_once`` and sleeps. Exposes Prometheus metrics on
``API_RULESET_PULLER_METRICS_PORT`` (default 9104) so the
``RulesetPullFailures`` / ``RulesetStale`` alerts can fire.

Master flag ``API_RULESET_PULLER_ENABLED`` gates rotation work; when
off the worker still starts (so docker-compose stays uniform) but
``run_once`` returns ``disabled`` without touching the DB.
"""
from __future__ import annotations

import asyncio
from typing import Final

import structlog
from prometheus_client import start_http_server

from app.config import Settings, get_settings
from app.db import close_engine, get_sessionmaker, init_engine
from app.logging import setup_logging
from app.services.ruleset.puller import pull_all

log = structlog.get_logger("ruleset.worker")

DEFAULT_METRICS_PORT: Final = 9104


async def run_once(settings: Settings) -> str:
    """One scan over all enabled sources. Returns ``ok|disabled|error``."""
    if not settings.ruleset_puller_enabled:
        return "disabled"
    sm = get_sessionmaker()
    async with sm() as session:
        async with session.begin():
            outcomes = await pull_all(
                session, timeout_sec=settings.ruleset_http_timeout_sec
            )
    n_err = sum(1 for o in outcomes if o.result == "error")
    n_ok = sum(1 for o in outcomes if o.result == "ok")
    n_unchanged = sum(1 for o in outcomes if o.result == "unchanged")
    log.info(
        "ruleset.worker.tick",
        ok=n_ok,
        unchanged=n_unchanged,
        error=n_err,
        total=len(outcomes),
    )
    return "ok" if n_err == 0 else "error"


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    start_http_server(settings.ruleset_puller_metrics_port)
    log.info(
        "ruleset.worker.start",
        interval_sec=settings.ruleset_pull_interval_sec,
        enabled=settings.ruleset_puller_enabled,
    )
    try:
        while True:
            try:
                await run_once(settings)
            except Exception:  # noqa: BLE001 — never let one tick kill the loop
                log.exception("ruleset.worker.tick_failed")
            await asyncio.sleep(settings.ruleset_pull_interval_sec)
    finally:
        await close_engine()
        log.info("ruleset.worker.stop")


if __name__ == "__main__":
    asyncio.run(main())
