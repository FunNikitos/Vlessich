"""MTProto rotation broadcaster (Stage 10).

Consumes ``mtproto:rotated`` Redis stream and fans out HMAC-signed POSTs
to the bot ``/internal/notify/mtproto_rotated`` endpoint, one per
affected Telegram chat.

Affected-chat resolution:

* ``scope='user'``: the single ``user_id`` from the event payload.
* ``scope='shared'``: every ``users.tg_id`` with an ACTIVE/TRIAL
  subscription. Crude (some users may not actually use MTProto), but
  there is no per-user issue log yet (deferred — see plan-stage-10).

Rate-limiting / idempotency / cooldown all live in
``app.services.mtproto_broadcast`` (Redis-backed). Per-event lifecycle:

1. XREADGROUP one entry.
2. Resolve the per-chat list.
3. For each chat:
   - skip + count(``duplicate``) if idempotency marker exists;
   - skip + count(``cooldown``) if cooldown marker exists;
   - try acquire RL slot — on miss, count(``throttled``) and break
     (so the same event is retried on next poll without losing the
     remaining chats);
   - POST to bot; on 2xx mark sent + count(``ok``); on 4xx
     count(``failed``) and proceed; on 5xx/network release
     idempotency + break (reattempt next tick).
4. XACK on full success or after a ``failed``/``duplicate``/``cooldown``
   pass; XACK on partial-throttled is intentionally skipped so the
   message is re-delivered next tick.

Worker survives any per-tick exception (logs + retries on next poll).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from typing import Any, Final

import aiohttp
import orjson
import structlog
from prometheus_client import start_http_server
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import close_engine, get_sessionmaker, init_engine
from app.logging import setup_logging
from app.metrics import MTPROTO_BROADCAST_SENT_TOTAL
from app.models import Subscription
from app.services.mtproto_broadcast import (
    STREAM_GROUP,
    STREAM_KEY,
    acquire_chat_send_slot,
    check_cooldown,
    check_idempotency,
    ensure_consumer_group,
    mark_sent,
    release_idempotency,
)

log = structlog.get_logger("mtproto.broadcaster")

METRICS_PORT: Final = 9103
CONSUMER_NAME: Final = "broadcaster-1"
POLL_BLOCK_MS: Final = 5000
POLL_BATCH: Final = 1


async def _resolve_recipients(
    session: AsyncSession, *, scope: str, user_id_raw: str
) -> list[int]:
    if scope == "user":
        if not user_id_raw:
            return []
        try:
            return [int(user_id_raw)]
        except ValueError:
            return []
    rows = await session.execute(
        select(Subscription.user_id)
        .where(Subscription.status.in_(("ACTIVE", "TRIAL")))
        .distinct()
    )
    return [int(uid) for (uid,) in rows.all()]


def _sign(secret: bytes, method: str, path: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    msg = f"{method}\n{path}\n{ts}\n".encode() + body
    sig = hmac.new(secret, msg, hashlib.sha256).hexdigest()
    return {"x-vlessich-ts": ts, "x-vlessich-sig": sig}


async def _post_to_bot(
    session: aiohttp.ClientSession,
    *,
    url: str,
    path: str,
    secret: bytes,
    payload: dict[str, Any],
) -> int:
    body = orjson.dumps(payload)
    headers = _sign(secret, "POST", path, body)
    headers["content-type"] = "application/json"
    async with session.post(url, data=body, headers=headers) as resp:
        # Drain body to free the connection back to the pool.
        await resp.read()
        return resp.status


async def _process_event(
    *,
    settings: Settings,
    redis: Redis,
    http: aiohttp.ClientSession,
    secret: bytes,
    fields: dict[str, str],
) -> str:
    """Returns one of ``ok|partial|skipped`` (drives XACK decision)."""
    event_id = fields.get("event_id", "")
    scope = fields.get("scope", "")
    user_id_raw = fields.get("user_id", "")
    if not event_id or scope not in ("shared", "user"):
        log.warning("mtproto.broadcaster.bad_event", fields=fields)
        return "skipped"

    sm = get_sessionmaker()
    async with sm() as session:
        recipients = await _resolve_recipients(
            session, scope=scope, user_id_raw=user_id_raw
        )

    notify_url = settings.mtg_broadcast_bot_notify_url
    notify_path = "/" + notify_url.split("/", 3)[-1] if "//" in notify_url else notify_url
    full = "ok"

    for tg_id in recipients:
        if await check_idempotency(redis, event_id, tg_id) is False:
            MTPROTO_BROADCAST_SENT_TOTAL.labels(status="duplicate").inc()
            continue
        if await check_cooldown(redis, tg_id):
            await release_idempotency(redis, event_id, tg_id)
            MTPROTO_BROADCAST_SENT_TOTAL.labels(status="cooldown").inc()
            continue
        if not await acquire_chat_send_slot(redis, tg_id):
            await release_idempotency(redis, event_id, tg_id)
            MTPROTO_BROADCAST_SENT_TOTAL.labels(status="throttled").inc()
            full = "partial"
            break

        payload = {
            "event_id": event_id,
            "scope": scope,
            "tg_id": tg_id,
            "emitted_at": fields.get("emitted_at", ""),
        }
        try:
            status_code = await _post_to_bot(
                http,
                url=notify_url,
                path=notify_path,
                secret=secret,
                payload=payload,
            )
        except Exception:  # noqa: BLE001 — network/timeout
            await release_idempotency(redis, event_id, tg_id)
            MTPROTO_BROADCAST_SENT_TOTAL.labels(status="failed").inc()
            log.exception(
                "mtproto.broadcaster.post_failed", tg_id=tg_id, event_id=event_id
            )
            full = "partial"
            break

        if 200 <= status_code < 300:
            await mark_sent(redis, tg_id)
            MTPROTO_BROADCAST_SENT_TOTAL.labels(status="ok").inc()
            log.info(
                "mtproto.broadcaster.sent",
                tg_id=tg_id,
                event_id=event_id,
                scope=scope,
            )
        elif 400 <= status_code < 500:
            # Don't release idempotency — bot rejected this payload, retry won't help.
            MTPROTO_BROADCAST_SENT_TOTAL.labels(status="failed").inc()
            log.warning(
                "mtproto.broadcaster.bot_4xx",
                tg_id=tg_id,
                event_id=event_id,
                status=status_code,
            )
        else:
            await release_idempotency(redis, event_id, tg_id)
            MTPROTO_BROADCAST_SENT_TOTAL.labels(status="failed").inc()
            log.warning(
                "mtproto.broadcaster.bot_5xx",
                tg_id=tg_id,
                event_id=event_id,
                status=status_code,
            )
            full = "partial"
            break

    return full


async def run_loop(
    settings: Settings, redis: Redis, http: aiohttp.ClientSession
) -> None:
    await ensure_consumer_group(redis)
    secret = settings.internal_secret.get_secret_value().encode()
    while True:
        try:
            entries = await redis.xreadgroup(
                groupname=STREAM_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_KEY: ">"},
                count=POLL_BATCH,
                block=POLL_BLOCK_MS,
            )
        except Exception:  # noqa: BLE001
            log.exception("mtproto.broadcaster.xread_failed")
            await asyncio.sleep(1.0)
            continue

        if not entries:
            continue

        for _stream_name, items in entries:
            for entry_id, fields in items:
                eid_str = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                norm: dict[str, str] = {}
                for k, v in fields.items():
                    kk = k.decode() if isinstance(k, bytes) else k
                    vv = v.decode() if isinstance(v, bytes) else v
                    norm[kk] = vv
                try:
                    result = await _process_event(
                        settings=settings,
                        redis=redis,
                        http=http,
                        secret=secret,
                        fields=norm,
                    )
                except Exception:  # noqa: BLE001
                    log.exception(
                        "mtproto.broadcaster.process_failed", entry_id=eid_str
                    )
                    continue
                if result in ("ok", "skipped"):
                    await redis.xack(STREAM_KEY, STREAM_GROUP, eid_str)
                # 'partial': leave un-ACK'd so it re-appears next tick.


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    start_http_server(METRICS_PORT)

    if not settings.mtg_broadcast_enabled:
        log.info("mtproto.broadcaster.disabled")
        # Keep container alive so docker doesn't restart-loop; just idle.
        try:
            while True:
                await asyncio.sleep(60)
        finally:
            await close_engine()
        return

    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=False)
    http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10.0, connect=3.0))
    log.info(
        "mtproto.broadcaster.start",
        url=settings.mtg_broadcast_bot_notify_url,
        rl_global=settings.mtg_broadcast_rl_global_per_sec,
        rl_per_chat_sec=settings.mtg_broadcast_rl_per_chat_sec,
    )
    try:
        await run_loop(settings, redis, http)
    finally:
        await http.close()
        await redis.aclose()
        await close_engine()
        log.info("mtproto.broadcaster.stop")


if __name__ == "__main__":
    asyncio.run(main())
