"""Integration tests for ``app.services.mtproto_broadcast`` (Stage 10).

Skipped unless ``VLESSICH_INTEGRATION_REDIS`` points to a live Redis
(e.g. ``redis://localhost:6379/15``). Covers:

1. ``emit_rotation_event`` XADDs with stable event_id and scope/user_id
   fields, honouring stream MAXLEN.
2. ``check_idempotency`` is atomic and idempotent (first call True,
   second call False within TTL).
3. ``release_idempotency`` allows re-claiming.
4. ``check_cooldown`` / ``mark_sent`` round-trip.
5. ``acquire_chat_send_slot`` enforces per-chat 1s floor and global
   30/s ceiling — 31st call in the same second rolls back the per-chat
   lock so another chat can still proceed.
"""
from __future__ import annotations

import os

os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)
os.environ.setdefault("API_ADMIN_JWT_SECRET", "j" * 32)
os.environ.setdefault("API_ADMIN_BCRYPT_COST", "4")
os.environ.setdefault("API_MTG_BROADCAST_RL_GLOBAL_PER_SEC", "30")
os.environ.setdefault("API_MTG_BROADCAST_RL_PER_CHAT_SEC", "1")
os.environ.setdefault("API_MTG_BROADCAST_COOLDOWN_SEC", "3600")
os.environ.setdefault("API_MTG_BROADCAST_IDEMPOTENCY_TTL_SEC", "86400")

import pytest

REDIS_URL = os.environ.get("VLESSICH_INTEGRATION_REDIS")
if REDIS_URL is None:
    pytest.skip(
        "set VLESSICH_INTEGRATION_REDIS=redis://.../N to run",
        allow_module_level=True,
    )

from redis.asyncio import Redis

from app.services.mtproto_broadcast import (
    STREAM_KEY,
    acquire_chat_send_slot,
    check_cooldown,
    check_idempotency,
    emit_rotation_event,
    mark_sent,
    release_idempotency,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def redis() -> Redis:
    r: Redis = Redis.from_url(REDIS_URL, decode_responses=True)
    await r.flushdb()
    try:
        yield r
    finally:
        await r.flushdb()
        await r.aclose()


async def test_emit_rotation_event_xadd(redis: Redis) -> None:
    eid = await emit_rotation_event(
        redis, scope="shared", secret_id="00000000-0000-0000-0000-000000000001"
    )
    assert eid
    entries = await redis.xrange(STREAM_KEY)
    assert len(entries) == 1
    _id, fields = entries[0]
    assert fields["event_id"] == eid
    assert fields["scope"] == "shared"
    assert fields["user_id"] == ""

    eid2 = await emit_rotation_event(
        redis,
        scope="user",
        secret_id="00000000-0000-0000-0000-000000000002",
        user_id=12345,
    )
    entries = await redis.xrange(STREAM_KEY)
    assert len(entries) == 2
    _id, fields2 = entries[1]
    assert fields2["event_id"] == eid2
    assert fields2["scope"] == "user"
    assert fields2["user_id"] == "12345"


async def test_idempotency_atomic(redis: Redis) -> None:
    assert await check_idempotency(redis, "evt1", 100) is True
    assert await check_idempotency(redis, "evt1", 100) is False
    assert await check_idempotency(redis, "evt1", 101) is True
    assert await check_idempotency(redis, "evt2", 100) is True


async def test_release_idempotency_allows_reclaim(redis: Redis) -> None:
    assert await check_idempotency(redis, "evt1", 42) is True
    await release_idempotency(redis, "evt1", 42)
    assert await check_idempotency(redis, "evt1", 42) is True


async def test_cooldown_round_trip(redis: Redis) -> None:
    assert await check_cooldown(redis, 7) is False
    await mark_sent(redis, 7)
    assert await check_cooldown(redis, 7) is True


async def test_rl_per_chat_floor(redis: Redis) -> None:
    assert await acquire_chat_send_slot(redis, 555) is True
    # Second immediate call for same chat blocked by per-chat TTL.
    assert await acquire_chat_send_slot(redis, 555) is False
    # Different chat still allowed.
    assert await acquire_chat_send_slot(redis, 556) is True


async def test_rl_global_ceiling(redis: Redis) -> None:
    # 30 distinct chats in the same second should succeed; 31st rolls back.
    outcomes = []
    for i in range(31):
        outcomes.append(await acquire_chat_send_slot(redis, 1000 + i))
    assert sum(1 for o in outcomes if o) == 30
    assert outcomes[-1] is False
    # The rolled-back chat key must be released so the chat can try next second.
    assert await redis.exists(f"mtproto_broadcast:rl:chat:{1030}") == 0
