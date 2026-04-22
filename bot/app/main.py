"""Bot runtime: Dispatcher, Bot, FSM storage, router wiring.

Supports both long-polling (dev) and webhook (prod) modes based on settings.
"""
from __future__ import annotations

import asyncio
from typing import Final

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiohttp import web
from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.handlers import router as root_router
from app.logging import log, setup_logging
from app.middlewares.throttling import ThrottlingMiddleware
from app.notify_server import start_notify_server

SHUTDOWN_TIMEOUT: Final = 10.0


def build_dispatcher(settings: Settings, redis: Redis) -> Dispatcher:
    storage = RedisStorage(redis=redis)
    dp = Dispatcher(storage=storage)
    # Expose the shared Redis client to handlers via dependency injection.
    dp["redis"] = redis
    msg_throttle = ThrottlingMiddleware(redis, rate=2, per_seconds=1, prefix="msg")
    cb_throttle = ThrottlingMiddleware(redis, rate=4, per_seconds=1, prefix="cb")
    dp.message.middleware(msg_throttle)
    dp.callback_query.middleware(cb_throttle)
    dp.include_router(root_router)
    return dp


def build_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=False)
    bot = build_bot(settings)
    dp = build_dispatcher(settings, redis)

    log.info("bot.start", env=settings.env, mode="webhook" if settings.use_webhook else "polling")
    notify_runner = None
    if settings.internal_notify_enabled:
        notify_runner = await start_notify_server(settings=settings, bot=bot)
    try:
        if settings.use_webhook:
            await _run_webhook(bot, dp, settings)
        else:
            await _run_polling(bot, dp)
    finally:
        if notify_runner is not None:
            await asyncio.wait_for(notify_runner.cleanup(), timeout=SHUTDOWN_TIMEOUT)
        await bot.session.close()
        await redis.aclose()
        log.info("bot.stop")


async def _run_polling(bot: Bot, dp: Dispatcher) -> None:
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot, handle_signals=True)


async def _run_webhook(bot: Bot, dp: Dispatcher, settings: Settings) -> None:
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    secret = settings.webhook_secret.get_secret_value() if settings.webhook_secret else None
    await bot.set_webhook(
        url=str(settings.webhook_url),
        secret_token=secret,
        drop_pending_updates=False,
        allowed_updates=dp.resolve_used_update_types(),
    )
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(
        app, path=settings.webhook_path
    )
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.webhook_host, port=settings.webhook_port)
    await site.start()

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        await asyncio.wait_for(runner.cleanup(), timeout=SHUTDOWN_TIMEOUT)
