"""Redis-backed rate limiter for /internal/codes/activate (TZ §5.5).

Sliding-window counter:
    INCR rl:code:{tg_id}, EXPIRE on first hit, reject when count > limit.

We expose a single ``check_rate_limit`` coroutine that returns the new
counter value so the caller can write a ``code_attempts(result='rl')`` row
without an extra round-trip.
"""
from __future__ import annotations

from redis.asyncio import Redis

from app.db import get_redis


async def check_code_rate_limit(
    redis: Redis, tg_id: int, *, limit: int, window_sec: int
) -> bool:
    """Return ``True`` if the request is within the limit; ``False`` if blocked.

    Fail-closed: any Redis error is propagated to the caller (activation is
    sensitive enough that we'd rather 5xx than silently bypass anti-abuse).
    """
    key = f"rl:code:{tg_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_sec)
    return count <= limit


async def sliding_window_check(*, key: str, limit: int, window_sec: int) -> bool:
    """Generic INCR+EXPIRE sliding-window guard. ``True`` means allowed."""
    redis = get_redis()
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_sec)
    return count <= limit
