"""Admin orders endpoints (Stage 11, Telegram Stars billing).

* ``GET  /admin/orders``            — paginated list (readonly+).
* ``GET  /admin/orders/{order_id}`` — detail (readonly+).
* ``POST /admin/orders/{order_id}/refund`` — superadmin. Issues HMAC POST
  to the bot ``/internal/refund/star_payment`` endpoint (only the bot
  process holds the Telegram bot token), then transitions the order to
  REFUNDED and revokes the subscription if appropriate.

Refund is two-phase: the bot side performs ``bot.refund_star_payment``
synchronously and returns 2xx on success. We do NOT mark REFUNDED until
the bot acknowledges, so a failed Telegram refund leaves the row PAID
and the admin can retry. The state transition is atomic in a single
transaction after the upstream call succeeds.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime
from typing import Annotated
from uuid import UUID

import aiohttp
import orjson
import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import AdminClaims, require_admin_role
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiCode, api_error
from app.models import Order
from app.schemas import OrderAdminOut, OrdersListOut, RefundOut
from app.services import billing

log = structlog.get_logger("admin.orders")

router = APIRouter(prefix="/admin/orders", tags=["admin", "billing"])

_READ_ROLES = ("superadmin", "support", "readonly")


def _to_out(order: Order) -> OrderAdminOut:
    return OrderAdminOut(
        id=str(order.id),
        user_id=order.user_id,
        plan_code=order.plan_code,
        amount_xtr=order.amount_xtr,
        currency=order.currency,
        status=order.status,
        telegram_payment_charge_id=order.telegram_payment_charge_id,
        provider_payment_charge_id=order.provider_payment_charge_id,
        created_at=order.created_at,
        paid_at=order.paid_at,
        refunded_at=order.refunded_at,
    )


@router.get("", response_model=OrdersListOut)
async def list_orders(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AdminClaims, Depends(require_admin_role(*_READ_ROLES))],
    status_filter: str | None = Query(default=None, alias="status"),
    user_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> OrdersListOut:
    base = select(Order)
    if status_filter is not None:
        if status_filter not in ("PENDING", "PAID", "REFUNDED", "FAILED"):
            raise api_error(
                status.HTTP_400_BAD_REQUEST,
                ApiCode.INVALID_REQUEST,
                "invalid status filter",
            )
        base = base.where(Order.status == status_filter)
    if user_id is not None:
        base = base.where(Order.user_id == user_id)

    total = await session.scalar(
        select(func.count()).select_from(base.subquery())
    )
    rows = (
        await session.scalars(
            base.order_by(Order.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return OrdersListOut(items=[_to_out(o) for o in rows], total=int(total or 0))


@router.get("/{order_id}", response_model=OrderAdminOut)
async def get_order(
    order_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AdminClaims, Depends(require_admin_role(*_READ_ROLES))],
) -> OrderAdminOut:
    order = await session.scalar(select(Order).where(Order.id == order_id))
    if order is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiCode.ORDER_NOT_FOUND, "order not found"
        )
    return _to_out(order)


def _sign_headers(secret: bytes, method: str, path: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    msg = f"{method}\n{path}\n{ts}\n".encode() + body
    sig = hmac.new(secret, msg, hashlib.sha256).hexdigest()
    return {
        "x-vlessich-ts": ts,
        "x-vlessich-sig": sig,
        "content-type": "application/json",
    }


async def _push_refund_to_bot(
    settings: Settings, *, tg_id: int, telegram_charge_id: str
) -> None:
    url = settings.billing_refund_bot_notify_url
    if not url:
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiCode.PAYMENT_VERIFICATION_FAILED,
            "refund bot URL not configured",
        )
    path = "/" + url.split("/", 3)[-1] if "//" in url else url
    body = orjson.dumps(
        {"tg_id": tg_id, "telegram_payment_charge_id": telegram_charge_id}
    )
    secret = settings.internal_secret.get_secret_value().encode()
    headers = _sign_headers(secret, "POST", path, body)
    timeout = aiohttp.ClientTimeout(total=10.0, connect=3.0)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as http:
            async with http.post(url, data=body, headers=headers) as resp:
                text = await resp.text()
                if not (200 <= resp.status < 300):
                    log.warning(
                        "admin.orders.refund.bot_error",
                        status=resp.status,
                        body=text[:200],
                    )
                    raise api_error(
                        status.HTTP_502_BAD_GATEWAY,
                        ApiCode.PAYMENT_VERIFICATION_FAILED,
                        "bot refund failed",
                    )
    except aiohttp.ClientError as exc:
        log.exception("admin.orders.refund.network_error")
        raise api_error(
            status.HTTP_502_BAD_GATEWAY,
            ApiCode.PAYMENT_VERIFICATION_FAILED,
            "bot refund network error",
        ) from exc


@router.post("/{order_id}/refund", response_model=RefundOut)
async def refund_order(
    order_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    claims: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> RefundOut:
    # Pre-flight read: verify order exists, is PAID, and has a charge id
    # before we hit the bot. Avoids unnecessary upstream call on stale UI.
    order = await session.scalar(select(Order).where(Order.id == order_id))
    if order is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiCode.ORDER_NOT_FOUND, "order not found"
        )
    if order.status == "REFUNDED":
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiCode.ORDER_ALREADY_REFUNDED,
            "order already refunded",
        )
    if order.status != "PAID":
        raise api_error(
            status.HTTP_409_CONFLICT, ApiCode.ORDER_NOT_PAID, "order not paid"
        )
    if not order.telegram_payment_charge_id:
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiCode.PAYMENT_VERIFICATION_FAILED,
            "order has no telegram_payment_charge_id",
        )

    # Phase 1: ask the bot to perform the actual Stars refund.
    await _push_refund_to_bot(
        settings,
        tg_id=order.user_id,
        telegram_charge_id=order.telegram_payment_charge_id,
    )

    # Phase 2: transition state in DB.
    try:
        refunded_order, revoked = await billing.refund(
            session, order_id=order_id, admin_id=UUID(claims.sub)
        )
    except billing.BillingError as exc:
        # Bot already refunded — surface error to admin so they can
        # reconcile manually. Audit log + bot logs both record the upstream success.
        log.error(
            "admin.orders.refund.db_failed_after_bot",
            order_id=str(order_id),
            code=str(exc.code),
        )
        raise api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            exc.code,
            "refund db transition failed after bot refund",
        ) from exc

    return RefundOut(order_id=str(refunded_order.id), subscription_revoked=revoked)
