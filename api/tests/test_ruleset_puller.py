"""Puller service tests with in-memory fetcher (Stage 12)."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RulesetSnapshot, RulesetSource
from app.services.ruleset.puller import PullOutcome, pull_all, pull_source


class _FakeFetcher:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def __call__(self, url: str, *, timeout_sec: float) -> str:
        self.calls.append(url)
        return self.responses[url]


@pytest.mark.asyncio
async def test_pull_source_ok_inserts_snapshot(session: AsyncSession) -> None:
    src = RulesetSource(
        id=uuid4(),
        name="af",
        kind="antifilter",
        url="https://example.test/list",
        category="ru",
        is_enabled=True,
    )
    session.add(src)
    await session.flush()

    fetcher = _FakeFetcher({"https://example.test/list": "sber.ru\nyandex.ru\n"})
    outcome = await pull_source(
        session, src, fetcher=fetcher, timeout_sec=5.0
    )
    assert outcome.result == "ok"
    assert outcome.domain_count == 2

    rows = (await session.scalars(select(RulesetSnapshot))).all()
    assert len(rows) == 1
    assert rows[0].is_current is True
    assert rows[0].domain_count == 2
    assert src.last_pulled_at is not None
    assert src.last_error is None


@pytest.mark.asyncio
async def test_pull_source_unchanged_on_same_sha(session: AsyncSession) -> None:
    src = RulesetSource(
        id=uuid4(),
        name="af",
        kind="antifilter",
        url="https://example.test/list",
        category="ru",
        is_enabled=True,
    )
    session.add(src)
    await session.flush()

    payload = "sber.ru\n"
    fetcher = _FakeFetcher({"https://example.test/list": payload})

    o1 = await pull_source(session, src, fetcher=fetcher, timeout_sec=5.0)
    o2 = await pull_source(session, src, fetcher=fetcher, timeout_sec=5.0)
    assert o1.result == "ok"
    assert o2.result == "unchanged"

    rows = (await session.scalars(select(RulesetSnapshot))).all()
    assert len(rows) == 1
    assert rows[0].sha256 == hashlib.sha256(payload.encode()).hexdigest()


@pytest.mark.asyncio
async def test_pull_source_rotates_current_on_new_content(
    session: AsyncSession,
) -> None:
    src = RulesetSource(
        id=uuid4(),
        name="af",
        kind="antifilter",
        url="https://example.test/list",
        category="ru",
        is_enabled=True,
    )
    session.add(src)
    await session.flush()

    fetcher = _FakeFetcher({"https://example.test/list": "a.ru\n"})
    await pull_source(session, src, fetcher=fetcher, timeout_sec=5.0)
    fetcher.responses["https://example.test/list"] = "a.ru\nb.ru\n"
    await pull_source(session, src, fetcher=fetcher, timeout_sec=5.0)

    rows = (
        await session.scalars(
            select(RulesetSnapshot).order_by(RulesetSnapshot.fetched_at)
        )
    ).all()
    assert len(rows) == 2
    assert rows[0].is_current is False
    assert rows[1].is_current is True
    assert rows[1].domain_count == 2


@pytest.mark.asyncio
async def test_pull_source_marks_error_on_parse_failure(
    session: AsyncSession,
) -> None:
    src = RulesetSource(
        id=uuid4(),
        name="custom-bad",
        kind="custom",
        url="file:///definitely/missing/path.yml",
        category="ru",
        is_enabled=True,
    )
    session.add(src)
    await session.flush()

    fetcher = _FakeFetcher({})  # not called — file:// reads locally
    outcome = await pull_source(
        session, src, fetcher=fetcher, timeout_sec=5.0
    )
    assert outcome.result == "error"
    assert src.last_error is not None


@pytest.mark.asyncio
async def test_pull_all_skips_disabled(session: AsyncSession) -> None:
    a = RulesetSource(
        id=uuid4(),
        name="enabled",
        kind="antifilter",
        url="https://example.test/a",
        category="ru",
        is_enabled=True,
    )
    b = RulesetSource(
        id=uuid4(),
        name="disabled",
        kind="antifilter",
        url="https://example.test/b",
        category="ru",
        is_enabled=False,
    )
    session.add_all([a, b])
    await session.flush()

    fetcher = _FakeFetcher({"https://example.test/a": "sber.ru\n"})
    outcomes = await pull_all(session, fetcher=fetcher, timeout_sec=5.0)
    # Only the enabled source should have been fetched.
    assert fetcher.calls == ["https://example.test/a"]
    assert len(outcomes) == 1
    assert outcomes[0].result == "ok"
