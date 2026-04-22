"""MTProto rotation broadcast service (Stage 10).

Pipeline:

* ``emit_rotation_event(scope, secret_id, user_id?)`` — XADD onto Redis
  stream ``mtproto:rotated`` with a stable ``event_id`` (uuid4 hex)
  and metadata sufficient for the broadcaster to fan out DMs.
* ``acquire_chat_send_slot(redis, tg_id)`` — acquire global + per-chat
  rate-limit tokens (Telegram bot ceiling: 30 msg/s global, 1 msg/s
  per chat). Returns ``True`` if the slot was acquired, ``False`` if
  the chat is currently throttled (caller should reschedule, NOT
  XACK).
* ``check_idempotency(redis, event_id, tg_id)`` — atomic SET NX with
  TTL. Returns ``True`` if THIS broadcaster instance now owns the
  (event, chat) pair, ``False`` if a previous attempt already
  completed.
* ``check_cooldown(redis, tg_id)`` — TTL probe. Returns ``True`` if
  the chat is in cooldown (skip), ``False`` if free to send.
* ``mark_sent(redis, tg_id)`` — set cooldown marker after a
  successful DM.

All Redis keys live under the ``mtproto_broadcast:`` namespace so they
can be scanned/flushed independently from FSM and rate-limiters of
other subsystems.

The service is import-safe with ``redis_url`` unset: keys are still
constructed but every method requires a live ``redis.asyncio.Redis``
client passed in by the caller. Workers bring their own client; tests
inject a fakeredis instance.
"""
from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Final, Literal

import structlog
from redis.asyncio import Redis

from app.config import get_settings

log = structlog.get_logger("mtproto.broadcast")

STREAM_KEY: Final = "mtproto:rotated"
STREAM_GROUP: Final = "broadcast"
STREAM_CONSUMER: Final = "broadcaster-1"

_NS: Final = "mtproto_broadcast"


def _idem_key(event_id: str, tg_id: int) -> str:
    return f"{_NS}:idem:{event_id}:{tg_id}"


def _cooldown_key(tg_id: int) -> str:
    return f"{_NS}:cooldown:{tg_id}"


def _rl_global_key() -> str:
    """Token-bucket key for global RL (per second, sliding via INCR + EXPIRE)."""
    second = int(time.time())
    return f"{_NS}:rl:global:{second}"


def _rl_chat_key(tg_id: int) -> str:
    return f"{_NS}:rl:chat:{tg_id}"


async def emit_rotation_event(
    redis: Redis,
    *,
    scope: Literal["shared", "user"],
    secret_id: str,
    user_id: int | None = None,
    event_id: str | None = None,
) -> str:
    """XADD a rotation event onto the broadcast stream.

    Returns the ``event_id`` used (caller should log/audit). Caller is
    responsible for not emitting events when ``mtg_broadcast_enabled``
    is False (the broadcaster will idle anyway, but XADD'ing wastes
    Redis memory).
    """
    settings = get_settings()
    eid = event_id or uuid.uuid4().hex
    fields = {
        "event_id": eid,
        "scope": scope,
        "secret_id": str(secret_id),
        "user_id": "" if user_id is None else str(user_id),
        "emitted_at": datetime.now(UTC).isoformat(),
    }
    await redis.xadd(
        STREAM_KEY,
        fields,
        maxlen=settings.mtg_broadcast_stream_maxlen,
        approximate=True,
    )
    log.info(
        "mtproto.broadcast.emitted",
        event_id=eid,
        scope=scope,
        secret_id=str(secret_id),
        user_id=user_id,
    )
    return eid


async def ensure_consumer_group(redis: Redis) -> None:
    """Create the consumer group if missing. Idempotent."""
    try:
        await redis.xgroup_create(
            STREAM_KEY, STREAM_GROUP, id="0", mkstream=True
        )
    except Exception as exc:  # noqa: BLE001 — redis raises a string-typed BUSYGROUP
        if "BUSYGROUP" not in str(exc):
            raise


async def check_cooldown(redis: Redis, tg_id: int) -> bool:
    """Returns True if the chat is currently in cooldown (skip the DM)."""
    return bool(await redis.exists(_cooldown_key(tg_id)))


async def mark_sent(redis: Redis, tg_id: int) -> None:
    settings = get_settings()
    await redis.set(
        _cooldown_key(tg_id),
        b"1",
        ex=settings.mtg_broadcast_cooldown_sec,
    )


async def check_idempotency(redis: Redis, event_id: str, tg_id: int) -> bool:
    """Atomic SET NX. Returns True if this attempt owns the slot, False if
    it was already claimed by a previous attempt (skip + XACK).
    """
    settings = get_settings()
    acquired = await redis.set(
        _idem_key(event_id, tg_id),
        b"1",
        nx=True,
        ex=settings.mtg_broadcast_idempotency_ttl_sec,
    )
    return bool(acquired)


async def release_idempotency(redis: Redis, event_id: str, tg_id: int) -> None:
    """Drop the idempotency marker so a retry can re-attempt this chat."""
    await redis.delete(_idem_key(event_id, tg_id))


async def acquire_chat_send_slot(redis: Redis, tg_id: int) -> bool:
    """Acquire global + per-chat RL tokens.

    Returns True on success, False if either limit is exhausted.
    Caller should NOT XACK on False — reschedule by NACK / re-XREAD.
    """
    settings = get_settings()
    # Per-chat: SET NX with TTL = mtg_broadcast_rl_per_chat_sec.
    chat_key = _rl_chat_key(tg_id)
    chat_ok = await redis.set(
        chat_key,
        b"1",
        nx=True,
        ex=settings.mtg_broadcast_rl_per_chat_sec,
    )
    if not chat_ok:
        return False
    # Global: per-second INCR bucket.
    g_key = _rl_global_key()
    count = await redis.incr(g_key)
    if count == 1:
        await redis.expire(g_key, 2)
    if count > settings.mtg_broadcast_rl_global_per_sec:
        # Roll back per-chat lock so a different chat can proceed
        # (we don't really need to; the cap will reset next second).
        await redis.delete(chat_key)
        return False
    return True
