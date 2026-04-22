"""Ruleset puller — fetch external feeds, compute sha256, upsert snapshot.

The puller is the only I/O surface of :mod:`app.services.ruleset`. Tests
mock the HTTP fetcher; parsing/builder are exercised separately.

Algorithm per source (see TZ §8.2):

1. ``custom`` kind: read ``infra/smart-routing/custom-ru.yml`` from disk
   (or whatever the operator pointed ``url`` at if it's a ``file://``
   URI). Otherwise GET ``source.url`` with ``API_RULESET_HTTP_TIMEOUT_SEC``.
2. Compute ``sha256`` of the raw payload. If a snapshot with the same
   ``(source_id, sha256)`` already exists → mark its row ``is_current``
   and demote others (no new row, ``unchanged`` outcome).
3. Else — parse to validate, INSERT new ``RulesetSnapshot``, set it
   ``is_current``, demote previous current.
4. On any exception — write ``last_error`` on the source, leave
   snapshots untouched, increment ``error`` counter.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import (
    RULESET_DOMAIN_COUNT,
    RULESET_LAST_PULL_TIMESTAMP,
    RULESET_PULL_TOTAL,
)
from app.models import RulesetSnapshot, RulesetSource
from app.services.ruleset.parsers import RulesetParseError, parse_by_kind

log = structlog.get_logger("ruleset.puller")

CUSTOM_LOCAL_PATH = Path("infra/smart-routing/custom-ru.yml")


class Fetcher(Protocol):
    async def __call__(self, url: str, *, timeout_sec: float) -> str: ...


async def http_fetcher(url: str, *, timeout_sec: float) -> str:
    """Default fetcher: HTTP GET → text. ``file://`` URIs are read locally."""
    if url.startswith("file://"):
        return Path(url[len("file://") :]).read_text(encoding="utf-8")
    async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def _read_custom(source: RulesetSource) -> str:
    """Custom source body — operator's local YAML file."""
    if source.url and source.url.startswith("file://"):
        return Path(source.url[len("file://") :]).read_text(encoding="utf-8")
    if source.url:
        # Operator pointed at an external custom YAML; honour it via fetcher.
        raise _NeedsHttp(source.url)
    return CUSTOM_LOCAL_PATH.read_text(encoding="utf-8")


class _NeedsHttp(Exception):
    """Internal control-flow signal for custom sources with HTTP urls."""

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.url = url


@dataclass(frozen=True, slots=True)
class PullOutcome:
    source_id: str
    result: str  # ok | unchanged | error
    domain_count: int = 0
    sha256: str = ""
    error: str | None = None


async def pull_source(
    session: AsyncSession,
    source: RulesetSource,
    *,
    fetcher: Fetcher,
    timeout_sec: float,
    now: datetime | None = None,
) -> PullOutcome:
    """Fetch, parse, upsert. Caller owns the outer transaction."""
    when = now or datetime.now(UTC)
    try:
        if source.kind == "custom":
            try:
                raw = _read_custom(source)
            except _NeedsHttp as need:
                raw = await fetcher(need.url, timeout_sec=timeout_sec)
        else:
            assert source.url is not None  # enforced by check constraint
            raw = await fetcher(source.url, timeout_sec=timeout_sec)

        parsed = parse_by_kind(source.kind, raw)
        sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    except (httpx.HTTPError, RulesetParseError, OSError) as exc:
        source.last_error = f"{type(exc).__name__}: {exc}"[:1000]
        source.updated_at = when
        RULESET_PULL_TOTAL.labels(source=source.name, result="error").inc()
        log.warning(
            "ruleset.pull.error",
            source=source.name,
            kind=source.kind,
            error=str(exc)[:200],
        )
        return PullOutcome(
            source_id=str(source.id), result="error", error=str(exc)[:200]
        )

    existing = await session.scalar(
        select(RulesetSnapshot).where(
            RulesetSnapshot.source_id == source.id,
            RulesetSnapshot.sha256 == sha,
        )
    )
    if existing is not None:
        # Same content — make sure it's the current one.
        if not existing.is_current:
            await session.execute(
                update(RulesetSnapshot)
                .where(
                    RulesetSnapshot.source_id == source.id,
                    RulesetSnapshot.is_current.is_(True),
                )
                .values(is_current=False)
            )
            existing.is_current = True
        source.last_pulled_at = when
        source.last_error = None
        source.updated_at = when
        RULESET_PULL_TOTAL.labels(source=source.name, result="unchanged").inc()
        RULESET_DOMAIN_COUNT.labels(
            source=source.name, category=source.category
        ).set(existing.domain_count)
        RULESET_LAST_PULL_TIMESTAMP.labels(source=source.name).set(when.timestamp())
        return PullOutcome(
            source_id=str(source.id),
            result="unchanged",
            domain_count=existing.domain_count,
            sha256=sha,
        )

    # New content — demote previous current, insert fresh row.
    await session.execute(
        update(RulesetSnapshot)
        .where(
            RulesetSnapshot.source_id == source.id,
            RulesetSnapshot.is_current.is_(True),
        )
        .values(is_current=False)
    )
    snap = RulesetSnapshot(
        source_id=source.id,
        sha256=sha,
        domain_count=parsed.domain_count,
        raw=raw,
        is_current=True,
        fetched_at=when,
    )
    session.add(snap)
    source.last_pulled_at = when
    source.last_error = None
    source.updated_at = when

    RULESET_PULL_TOTAL.labels(source=source.name, result="ok").inc()
    RULESET_DOMAIN_COUNT.labels(
        source=source.name, category=source.category
    ).set(parsed.domain_count)
    RULESET_LAST_PULL_TIMESTAMP.labels(source=source.name).set(when.timestamp())
    log.info(
        "ruleset.pull.ok",
        source=source.name,
        kind=source.kind,
        domains=parsed.domain_count,
        skipped=parsed.skipped,
    )
    return PullOutcome(
        source_id=str(source.id),
        result="ok",
        domain_count=parsed.domain_count,
        sha256=sha,
    )


async def pull_all(
    session: AsyncSession,
    *,
    fetcher: Fetcher | None = None,
    timeout_sec: float = 30.0,
) -> list[PullOutcome]:
    """Iterate all enabled sources. Each pull runs in its own savepoint so
    one bad source cannot abort the others."""
    f = fetcher or http_fetcher
    sources = (
        await session.execute(
            select(RulesetSource).where(RulesetSource.is_enabled.is_(True))
        )
    ).scalars().all()
    outcomes: list[PullOutcome] = []
    for src in sources:
        async with session.begin_nested():
            outcomes.append(
                await pull_source(session, src, fetcher=f, timeout_sec=timeout_sec)
            )
    return outcomes


__all__ = [
    "Fetcher",
    "PullOutcome",
    "http_fetcher",
    "pull_source",
    "pull_all",
    "CUSTOM_LOCAL_PATH",
]
