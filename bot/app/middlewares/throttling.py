"""Redis-based per-user throttling middleware.

Sliding-window rate limiter (TZ §5.5). Replaces the previous in-memory
implementation so limits survive restarts and are shared across replicas.

Algorithm: ``INCR rl:{prefix}:{user_id}:{bucket}`` where ``bucket`` is the
current ``floor(unix_seconds / window)``. If returned counter exceeds
``rate``, the event is dropped. ``EXPIRE`` is set on first INCR so old
buckets evict automatically.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from redis.asyncio import Redis

from app.logging import log


class ThrottlingMiddleware(BaseMiddleware):
    """Drop events when user exceeds ``rate`` per ``per_seconds`` window.

    :param redis: ``redis.asyncio.Redis`` instance (already connected).
    :param rate: Allowed events per window.
    :param per_seconds: Window length, seconds.
    :param prefix: Redis key prefix (``msg`` / ``cb`` / ``code``).
    """

    def __init__(
        self,
        redis: Redis,
        *,
        rate: int = 2,
        per_seconds: int = 1,
        prefix: str = "msg",
    ) -> None:
        if rate < 1 or per_seconds < 1:
            raise ValueError("rate and per_seconds must be >= 1")
        self._redis = redis
        self._rate = rate
        self._per = per_seconds
        self._prefix = prefix

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        bucket = int(time.time() // self._per)
        key = f"rl:{self._prefix}:{user.id}:{bucket}"
        try:
            count = await self._redis.incr(key)
            if count == 1:
                # Keep the bucket for one extra window to avoid race where
                # EXPIRE arrives after the bucket has rolled over.
                await self._redis.expire(key, self._per * 2)
        except Exception:
            # Fail-open: if Redis is unreachable we let the event through
            # rather than silently dropping all traffic. The error is logged
            # and the global health check will catch the outage.
            log.warning("throttling.redis_error", key=key, exc_info=True)
            return await handler(event, data)

        if count > self._rate:
            log.info("throttling.dropped", user_id=user.id, prefix=self._prefix, count=count)
            return None
        return await handler(event, data)
