"""Tests for ``app.middlewares.throttling.ThrottlingMiddleware``."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import TelegramObject, User
from fakeredis.aioredis import FakeRedis

from app.middlewares.throttling import ThrottlingMiddleware


def _user(uid: int = 1) -> User:
    return User(id=uid, is_bot=False, first_name="t")


@pytest.fixture
async def redis():
    r = FakeRedis()
    yield r
    await r.aclose()


async def _call(mw: ThrottlingMiddleware, handler: AsyncMock, uid: int = 1) -> Any:
    event = MagicMock(spec=TelegramObject)
    return await mw(handler, event, {"event_from_user": _user(uid)})


async def test_passes_under_limit(redis: FakeRedis) -> None:
    mw = ThrottlingMiddleware(redis, rate=3, per_seconds=10)
    handler = AsyncMock(return_value="ok")
    for _ in range(3):
        assert await _call(mw, handler) == "ok"
    assert handler.await_count == 3


async def test_drops_over_limit(redis: FakeRedis) -> None:
    mw = ThrottlingMiddleware(redis, rate=2, per_seconds=10)
    handler = AsyncMock(return_value="ok")
    assert await _call(mw, handler) == "ok"
    assert await _call(mw, handler) == "ok"
    # Third call within window must be dropped.
    assert await _call(mw, handler) is None
    assert handler.await_count == 2


async def test_independent_per_user(redis: FakeRedis) -> None:
    mw = ThrottlingMiddleware(redis, rate=1, per_seconds=10)
    handler = AsyncMock(return_value="ok")
    assert await _call(mw, handler, uid=1) == "ok"
    assert await _call(mw, handler, uid=1) is None
    # Different user — independent counter.
    assert await _call(mw, handler, uid=2) == "ok"
    assert handler.await_count == 2


async def test_no_user_passes_through(redis: FakeRedis) -> None:
    mw = ThrottlingMiddleware(redis, rate=1, per_seconds=10)
    handler = AsyncMock(return_value="ok")
    event = MagicMock(spec=TelegramObject)
    # No event_from_user — system event.
    assert await mw(handler, event, {}) == "ok"


async def test_invalid_rate_raises() -> None:
    redis = FakeRedis()
    try:
        with pytest.raises(ValueError):
            ThrottlingMiddleware(redis, rate=0, per_seconds=1)
        with pytest.raises(ValueError):
            ThrottlingMiddleware(redis, rate=1, per_seconds=0)
    finally:
        await redis.aclose()


async def test_failopen_on_redis_error() -> None:
    """If Redis is unreachable, requests are let through (logged)."""
    broken = MagicMock()
    broken.incr = AsyncMock(side_effect=ConnectionError("redis down"))
    mw = ThrottlingMiddleware(broken, rate=1, per_seconds=10)
    handler = AsyncMock(return_value="ok")
    assert await _call(mw, handler) == "ok"
    assert handler.await_count == 1
