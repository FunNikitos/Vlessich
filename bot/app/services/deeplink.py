"""Deep-link payload capture/consume helpers.

When a user starts the bot with ``/start <payload>`` we cache the payload in
Redis under ``dl:{tg_id}`` (TTL 7 days). The first mutating call to backend
(``/internal/trials`` or ``/internal/codes/activate``) reads the value and
sends it as ``referral_source``; on success the key is dropped.
"""
from __future__ import annotations

from redis.asyncio import Redis

DEEPLINK_TTL_SEC = 7 * 24 * 60 * 60
_KEY = "dl:{tg_id}"
_MAX_LEN = 128


async def store_deeplink(redis: Redis, tg_id: int, payload: str) -> None:
    payload = payload.strip()
    if not payload:
        return
    if len(payload) > _MAX_LEN:
        payload = payload[:_MAX_LEN]
    await redis.set(_KEY.format(tg_id=tg_id), payload.encode(), ex=DEEPLINK_TTL_SEC)


async def consume_deeplink(redis: Redis, tg_id: int) -> str | None:
    raw = await redis.get(_KEY.format(tg_id=tg_id))
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


async def drop_deeplink(redis: Redis, tg_id: int) -> None:
    await redis.delete(_KEY.format(tg_id=tg_id))
