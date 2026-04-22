"""Bot HTTP endpoint(s) consumed by API workers (Stage 10).

Hosts a small aiohttp app on ``BOT_INTERNAL_NOTIFY_HOST:PORT`` separate
from the Telegram webhook. Currently exposes:

* ``POST /internal/notify/mtproto_rotated`` — called by API
  ``mtproto_broadcaster`` worker. Verifies HMAC (same scheme as
  Bot→API: header ``x-vlessich-sig`` = SHA-256 of
  ``METHOD\\nPATH\\nTS\\n + body``, clock skew ≤60s). Body:
  ``{event_id, scope, tg_id, emitted_at}``. Bot fetches the fresh
  deeplink via the existing API client and DMs it to the user.

The endpoint never re-raises Telegram errors back to the broadcaster:
it returns 200 OK with ``{"status": "skipped"}`` so the broadcaster's
idempotency marker stays in place and we don't re-flood the chat on
the next event. That matches the "fire-and-forget DM" semantics agreed
in plan-stage-10.md (out-of-scope: retry-after queue).
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Final

import orjson
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiohttp import web

from app.config import Settings
from app.logging import log
from app.services.api_client import ApiClient, ApiError
from app.texts import MTPROTO_ROTATED, REFUND_NOTICE

PATH: Final = "/internal/notify/mtproto_rotated"
MAX_SKEW_SEC: Final = 60


def _verify_signature(
    secret: bytes, *, method: str, path: str, ts: str, sig: str, body: bytes
) -> bool:
    try:
        ts_int = int(ts)
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - ts_int) > MAX_SKEW_SEC:
        return False
    msg = f"{method}\n{path}\n{ts}\n".encode() + body
    expected = hmac.new(secret, msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def build_app(*, settings: Settings, bot: Bot) -> web.Application:
    app = web.Application()
    secret = settings.api_internal_secret.get_secret_value().encode()

    async def handle_mtproto_rotated(request: web.Request) -> web.Response:
        if not settings.internal_notify_enabled:
            return web.json_response(
                {"code": "notification_disabled", "message": "off"}, status=503
            )
        body = await request.read()
        ts = request.headers.get("x-vlessich-ts", "")
        sig = request.headers.get("x-vlessich-sig", "")
        if not _verify_signature(
            secret,
            method="POST",
            path=settings.internal_notify_path,
            ts=ts,
            sig=sig,
            body=body,
        ):
            log.warning("notify.bad_signature", path=settings.internal_notify_path)
            return web.json_response(
                {"code": "bad_signature", "message": "bad sig"}, status=401
            )
        try:
            payload: dict[str, Any] = orjson.loads(body) if body else {}
        except orjson.JSONDecodeError:
            return web.json_response(
                {"code": "invalid_request", "message": "bad json"}, status=400
            )
        if not isinstance(payload, dict):
            return web.json_response(
                {"code": "invalid_request", "message": "bad json"}, status=400
            )
        try:
            tg_id = int(payload["tg_id"])
        except (KeyError, TypeError, ValueError):
            return web.json_response(
                {"code": "invalid_request", "message": "tg_id"}, status=400
            )
        scope = str(payload.get("scope", ""))
        event_id = str(payload.get("event_id", ""))
        if scope not in ("shared", "user"):
            return web.json_response(
                {"code": "invalid_request", "message": "scope"}, status=400
            )

        try:
            async with ApiClient() as api:
                mp = await api.get_mtproto(tg_id=tg_id, scope=scope)
        except ApiError as exc:
            log.warning(
                "notify.fetch_failed",
                tg_id=tg_id,
                event_id=event_id,
                api_code=exc.code,
                status=exc.status,
            )
            # Bot has nothing to send — tell broadcaster it was processed
            # so it doesn't retry forever.
            return web.json_response({"status": "skipped"}, status=200)

        try:
            await bot.send_message(
                tg_id,
                MTPROTO_ROTATED.format(
                    deeplink=mp.tg_deeplink, host=mp.host, port=mp.port
                ),
            )
        except TelegramAPIError as exc:
            log.warning(
                "notify.send_failed",
                tg_id=tg_id,
                event_id=event_id,
                error=str(exc),
            )
            return web.json_response({"status": "skipped"}, status=200)

        log.info(
            "notify.sent",
            tg_id=tg_id,
            event_id=event_id,
            scope=scope,
        )
        return web.json_response({"status": "ok"}, status=200)

    app.router.add_post(settings.internal_notify_path, handle_mtproto_rotated)

    async def handle_refund_star_payment(request: web.Request) -> web.Response:
        """API → Bot: perform ``bot.refund_star_payment`` + notify user.

        Invoked by ``POST /admin/orders/{id}/refund`` on the API side.
        Returns 200 on success so API can transition the order to
        REFUNDED. Any Telegram error maps to 502 so admin sees the
        failure and can retry without DB drift.
        """
        body = await request.read()
        ts = request.headers.get("x-vlessich-ts", "")
        sig = request.headers.get("x-vlessich-sig", "")
        if not _verify_signature(
            secret,
            method="POST",
            path=settings.internal_refund_path,
            ts=ts,
            sig=sig,
            body=body,
        ):
            log.warning("refund.bad_signature", path=settings.internal_refund_path)
            return web.json_response(
                {"code": "bad_signature", "message": "bad sig"}, status=401
            )
        try:
            payload: dict[str, Any] = orjson.loads(body) if body else {}
        except orjson.JSONDecodeError:
            return web.json_response(
                {"code": "invalid_request", "message": "bad json"}, status=400
            )
        if not isinstance(payload, dict):
            return web.json_response(
                {"code": "invalid_request", "message": "bad json"}, status=400
            )
        try:
            tg_id = int(payload["tg_id"])
            charge_id = str(payload["telegram_payment_charge_id"])
        except (KeyError, TypeError, ValueError):
            return web.json_response(
                {"code": "invalid_request", "message": "bad payload"},
                status=400,
            )
        if not charge_id:
            return web.json_response(
                {"code": "invalid_request", "message": "empty charge_id"},
                status=400,
            )
        try:
            await bot.refund_star_payment(
                user_id=tg_id, telegram_payment_charge_id=charge_id
            )
        except TelegramAPIError as exc:
            log.warning(
                "refund.telegram_error", tg_id=tg_id, error=str(exc)
            )
            return web.json_response(
                {"code": "payment_verification_failed", "message": str(exc)},
                status=502,
            )

        # Best-effort courtesy DM; failure here does NOT roll back the refund.
        try:
            await bot.send_message(tg_id, REFUND_NOTICE)
        except TelegramAPIError as exc:
            log.info("refund.notice_send_failed", tg_id=tg_id, error=str(exc))

        log.info("refund.done", tg_id=tg_id)
        return web.json_response({"status": "ok"}, status=200)

    app.router.add_post(settings.internal_refund_path, handle_refund_star_payment)
    return app


async def start_notify_server(
    *, settings: Settings, bot: Bot
) -> web.AppRunner:
    """Start the aiohttp app and return its runner so the caller can clean up."""
    app = build_app(settings=settings, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        host=settings.internal_notify_host,
        port=settings.internal_notify_port,
    )
    await site.start()
    log.info(
        "notify.start",
        host=settings.internal_notify_host,
        port=settings.internal_notify_port,
        path=settings.internal_notify_path,
        refund_path=settings.internal_refund_path,
    )
    return runner
