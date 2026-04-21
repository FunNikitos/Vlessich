"""Subscription expiry reminder worker.

Runs as a separate container (``docker-compose.dev.yml::reminders``). Every
``SCAN_INTERVAL_SEC`` seconds it scans ``subscriptions`` with ``expires_at``
in the next 24h and sends an idempotent reminder via Telegram for the
smallest bucket not yet recorded in ``reminder_log``.

Buckets (hours until expiry): 24, 6, 1. Idempotency is enforced by the
``reminder_log`` primary key ``(subscription_id, bucket)``.

The worker uses ``aiogram.Bot`` in send-only mode (no polling, no webhook).
Token is shared with the bot service via ``BOT_TOKEN`` env var.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import structlog
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import close_engine, get_sessionmaker, init_engine
from app.logging import setup_logging
from app.models import ReminderLog, Subscription

log = structlog.get_logger("reminders")

SCAN_INTERVAL_SEC: Final = 15 * 60
BUCKETS_HOURS: Final[tuple[tuple[str, int], ...]] = (("1h", 1), ("6h", 6), ("24h", 24))

_MESSAGES: Final[dict[str, str]] = {
    "24h": "⏰ Подписка истекает через 24 часа. Продли кодом или купи план.",
    "6h": "⏰ Подписка истекает через 6 часов.",
    "1h": "⚠️ Подписка истекает через час.",
}


@dataclass(slots=True, frozen=True)
class Reminder:
    user_id: int
    subscription_id: str
    bucket: str


def _choose_bucket(now: datetime, expires_at: datetime) -> str | None:
    remaining = expires_at - now
    for label, hours in BUCKETS_HOURS:
        if remaining <= timedelta(hours=hours):
            return label
    return None


async def _collect(session: AsyncSession, now: datetime) -> list[Reminder]:
    horizon = now + timedelta(hours=24)
    rows = await session.execute(
        select(Subscription).where(
            Subscription.status.in_(("ACTIVE", "TRIAL")),
            Subscription.expires_at.is_not(None),
            Subscription.expires_at <= horizon,
            Subscription.expires_at > now,
        )
    )
    pending: list[Reminder] = []
    for sub in rows.scalars():
        if sub.expires_at is None:
            continue
        bucket = _choose_bucket(now, sub.expires_at)
        if bucket is None:
            continue
        existing = await session.scalar(
            select(ReminderLog).where(
                ReminderLog.subscription_id == sub.id,
                ReminderLog.bucket == bucket,
            )
        )
        if existing is not None:
            continue
        pending.append(
            Reminder(user_id=sub.user_id, subscription_id=str(sub.id), bucket=bucket)
        )
    return pending


async def _send_and_record(bot: Bot, session: AsyncSession, rem: Reminder) -> None:
    try:
        await bot.send_message(rem.user_id, _MESSAGES[rem.bucket])
    except TelegramAPIError as exc:
        log.warning(
            "reminders.send_failed",
            user_id=rem.user_id,
            bucket=rem.bucket,
            error=str(exc),
        )
        return
    try:
        async with session.begin():
            session.add(
                ReminderLog(subscription_id=rem.subscription_id, bucket=rem.bucket)
            )
    except IntegrityError:
        # Duplicate from a parallel run — already logged by the other worker.
        log.info("reminders.duplicate", subscription_id=rem.subscription_id, bucket=rem.bucket)


async def run_once() -> int:
    """One pass; returns number of reminders actually sent."""
    now = datetime.now(UTC)
    sm = get_sessionmaker()
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN env var is required for reminders worker")
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    sent = 0
    try:
        async with sm() as session:
            pending = await _collect(session, now)
        for rem in pending:
            async with sm() as session:
                await _send_and_record(bot, session, rem)
                sent += 1
    finally:
        await bot.session.close()
    log.info("reminders.tick", scanned_at=now.isoformat(), sent=sent)
    return sent


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_engine(settings.database_url)
    log.info("reminders.start", interval_sec=SCAN_INTERVAL_SEC)
    try:
        while True:
            try:
                await run_once()
            except Exception:  # noqa: BLE001 — worker must survive any per-tick error
                log.exception("reminders.tick_failed")
            await asyncio.sleep(SCAN_INTERVAL_SEC)
    finally:
        await close_engine()
        log.info("reminders.stop")


if __name__ == "__main__":
    asyncio.run(main())
