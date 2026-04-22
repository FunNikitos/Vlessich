"""Bot ↔ API billing endpoints (Stage 11, Telegram Stars MVP).

Three HMAC-protected endpoints called by the bot during the Telegram
Stars purchase lifecycle:

* ``POST /internal/payments/plans``  — list active SKU catalog (XTR).
* ``POST /internal/payments/create_order`` — issue a PENDING order for
  the given user before ``bot.send_invoice``.
* ``POST /internal/payments/precheck`` — answer pre_checkout_query.
* ``POST /internal/payments/success`` — finalize on
  ``F.successful_payment``: PENDING → PAID, extend/issue Subscription.

All endpoints honour ``settings.billing_enabled``; when off, they
return ``409 BILLING_DISABLED`` so the bot can render a maintenance
message instead of a payment dialog.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiCode, api_error
from app.schemas import (
    CreateOrderIn,
    CreateOrderOut,
    PaymentSuccessIn,
    PaymentSuccessOut,
    PlanOut,
    PlansListOut,
    PrecheckIn,
)
from app.security import verify_internal_signature
from app.services import billing
from app.services.remnawave import RemnawaveClient, get_remnawave

router = APIRouter(
    prefix="/internal/payments",
    tags=["internal", "billing"],
    dependencies=[Depends(verify_internal_signature)],
)


def _ensure_enabled(settings: Settings) -> None:
    if not settings.billing_enabled:
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiCode.BILLING_DISABLED,
            "Платежи временно отключены.",
        )


def _map_billing_error(exc: billing.BillingError) -> Exception:
    code = exc.code
    if code == ApiCode.INVALID_PLAN:
        return api_error(status.HTTP_404_NOT_FOUND, code, "Тариф недоступен.")
    if code == ApiCode.ORDER_NOT_FOUND:
        return api_error(status.HTTP_404_NOT_FOUND, code, "Заказ не найден.")
    if code == ApiCode.ORDER_NOT_PENDING:
        return api_error(status.HTTP_409_CONFLICT, code, "Заказ не в ожидании оплаты.")
    if code == ApiCode.ORDER_NOT_PAID:
        return api_error(status.HTTP_409_CONFLICT, code, "Заказ не оплачен.")
    if code == ApiCode.ORDER_ALREADY_REFUNDED:
        return api_error(status.HTTP_409_CONFLICT, code, "Заказ уже возвращён.")
    if code == ApiCode.PAYMENT_AMOUNT_MISMATCH:
        return api_error(
            status.HTTP_409_CONFLICT, code, "Сумма не совпадает с заказом."
        )
    return api_error(status.HTTP_500_INTERNAL_SERVER_ERROR, code, "billing error")


@router.post("/plans", response_model=PlansListOut)
async def list_plans(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlansListOut:
    _ensure_enabled(settings)
    plans = await billing.list_active_plans(session)
    return PlansListOut(
        plans=[
            PlanOut(
                code=p.code,
                duration_days=p.duration_days,
                price_xtr=p.price_xtr,
                currency="XTR",
            )
            for p in plans
        ]
    )


@router.post("/create_order", response_model=CreateOrderOut)
async def create_order(
    payload: CreateOrderIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CreateOrderOut:
    _ensure_enabled(settings)
    try:
        draft = await billing.create_order(
            session,
            tg_id=payload.tg_id,
            plan_code=payload.plan_code,
            pending_ttl_sec=settings.billing_plan_ttl_pending_sec,
        )
    except billing.BillingError as exc:
        raise _map_billing_error(exc) from exc
    return CreateOrderOut(
        order_id=str(draft.order_id),
        invoice_payload=draft.invoice_payload,
        amount_xtr=draft.amount_xtr,
        currency="XTR",
        plan_code=draft.plan_code,
        duration_days=draft.duration_days,
    )


@router.post("/precheck")
async def precheck(
    payload: PrecheckIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, bool]:
    _ensure_enabled(settings)
    try:
        await billing.precheck(
            session,
            invoice_payload=payload.invoice_payload,
            amount_xtr=payload.amount_xtr,
        )
    except billing.BillingError as exc:
        raise _map_billing_error(exc) from exc
    return {"ok": True}


@router.post("/success", response_model=PaymentSuccessOut)
async def payment_success(
    payload: PaymentSuccessIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    remna: Annotated[RemnawaveClient, Depends(get_remnawave)],
) -> PaymentSuccessOut:
    _ensure_enabled(settings)
    try:
        result = await billing.mark_paid(
            session,
            invoice_payload=payload.invoice_payload,
            amount_xtr=payload.amount_xtr,
            telegram_payment_charge_id=payload.telegram_payment_charge_id,
            provider_payment_charge_id=payload.provider_payment_charge_id,
            remna=remna,
        )
    except billing.BillingError as exc:
        raise _map_billing_error(exc) from exc
    return PaymentSuccessOut(
        order_id=str(result.order_id),
        subscription_id=str(result.subscription_id),
        new_expires_at=result.new_expires_at,
    )
