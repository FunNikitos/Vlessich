"""Unit tests for bot deep-link cache helpers."""
from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("BOT_API_BASE_URL", "http://api")
os.environ.setdefault("BOT_API_INTERNAL_SECRET", "x" * 32)

import fakeredis.aioredis
import pytest

from app.services.deeplink import consume_deeplink, drop_deeplink, store_deeplink


@pytest.mark.asyncio
async def test_store_then_consume_roundtrip() -> None:
    r = fakeredis.aioredis.FakeRedis()
    await store_deeplink(r, 1, "ref_google_cpc")
    assert await consume_deeplink(r, 1) == "ref_google_cpc"


@pytest.mark.asyncio
async def test_consume_missing_returns_none() -> None:
    r = fakeredis.aioredis.FakeRedis()
    assert await consume_deeplink(r, 999) is None


@pytest.mark.asyncio
async def test_store_truncates_overlong_payload() -> None:
    r = fakeredis.aioredis.FakeRedis()
    await store_deeplink(r, 2, "x" * 500)
    got = await consume_deeplink(r, 2)
    assert got is not None
    assert len(got) <= 128


@pytest.mark.asyncio
async def test_store_empty_payload_is_noop() -> None:
    r = fakeredis.aioredis.FakeRedis()
    await store_deeplink(r, 3, "  ")
    assert await consume_deeplink(r, 3) is None


@pytest.mark.asyncio
async def test_drop_deletes_key() -> None:
    r = fakeredis.aioredis.FakeRedis()
    await store_deeplink(r, 4, "ref_abc")
    await drop_deeplink(r, 4)
    assert await consume_deeplink(r, 4) is None
