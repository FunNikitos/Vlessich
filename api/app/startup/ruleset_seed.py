"""Seed default ruleset sources (Stage 12).

Called from :mod:`app.main` lifespan. Idempotent: if a source with the
given name already exists, it's left alone (operators can tweak URL /
is_enabled / category without having seed overwrite them).

Three default sources (see docs/plan-stage-12.md T1 locked decisions):

* ``antifilter-domains``  — antifilter.network text list (RU).
* ``v2fly-geosite-ru``    — v2fly ``category-ru`` geosite.
* ``v2fly-geosite-ads``   — v2fly ``category-ads-all`` geosite.
* ``custom-ru``           — local ``infra/smart-routing/custom-ru.yml``.
"""
from __future__ import annotations

from typing import Iterable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RulesetSource

log = structlog.get_logger("ruleset.seed")


DEFAULT_SOURCES: tuple[dict[str, object], ...] = (
    {
        "name": "antifilter-domains",
        "kind": "antifilter",
        "url": "https://community.antifilter.download/list/domains.lst",
        "category": "ru",
        "is_enabled": True,
    },
    {
        "name": "v2fly-geosite-ru",
        "kind": "v2fly_geosite",
        "url": "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/category-ru",
        "category": "ru",
        "is_enabled": True,
    },
    {
        "name": "v2fly-geosite-ads",
        "kind": "v2fly_geosite",
        "url": "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/category-ads-all",
        "category": "ads",
        "is_enabled": True,
    },
    {
        "name": "custom-ru",
        "kind": "custom",
        "url": None,
        "category": "ru",
        "is_enabled": True,
    },
)


async def seed_default_ruleset_sources(
    session: AsyncSession,
    sources: Iterable[dict[str, object]] = DEFAULT_SOURCES,
) -> int:
    """Insert missing default sources. Returns the number of new rows."""
    inserted = 0
    for row in sources:
        name = str(row["name"])
        existing = await session.scalar(
            select(RulesetSource).where(RulesetSource.name == name)
        )
        if existing is not None:
            continue
        session.add(
            RulesetSource(
                name=name,
                kind=str(row["kind"]),
                url=row["url"] if row["url"] is None else str(row["url"]),
                category=str(row["category"]),
                is_enabled=bool(row["is_enabled"]),
            )
        )
        inserted += 1
    if inserted:
        await session.flush()
        log.info("ruleset.seed.ok", inserted=inserted)
    return inserted


__all__ = ["DEFAULT_SOURCES", "seed_default_ruleset_sources"]
