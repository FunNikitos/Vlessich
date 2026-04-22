"""Telegram Stars purchase flow (Stage 11).

Three handlers wire the Telegram Bot Payments API to the backend
billing service:

1. ``/buy`` (or callback ``buy:start``) — fetches active plans from the
   API, renders an inline keyboard, lets the user pick a SKU.
2. ``buy:plan:<code>`` callback — calls ``api.create_order`` and then
   ``bot.send_invoice(currency='XTR', provider_token='', payload=order_id)``.
3. ``pre_checkout_query`` — calls ``api.precheck_order`` to validate the
   pending order; answers ``ok=True/False`` accordingly.
4. ``F.successful_payment`` — calls ``api.notify_payment_success``;
   replies with ``PAYMENT_SUCCESS`` or ``PAYMENT_FAILED``.

Master flag ``BOT_BILLING_ENABLED`` short-circuits all entry points to
the ``BUY_DISABLED`` text so a single env toggle hides the surface.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from app.config import get_settings
from app.handlers._utils import resolve_cb
from app.logging import log
from app.services.api_client import ApiClient, ApiError, PlanInfo
from app.texts import (
    BUY_API_ERROR,
    BUY_DISABLED,
    BUY_INVOICE_DESCRIPTION,
    BUY_INVOICE_TITLE,
    BUY_PLAN_BUTTON,
    BUY_PLAN_LABEL,
    BUY_PLAN_NOT_FOUND,
    BUY_PROMPT,
    PAYMENT_FAILED,
    PAYMENT_SUCCESS,
)

router = Router(name="purchase")


def _plan_label(plan: PlanInfo) -> str:
    return BUY_PLAN_LABEL.get(plan.code, plan.code)


def _plans_kb(plans: list[PlanInfo]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for plan in plans:
        rows.append(
            [
                InlineKeyboardButton(
                    text=BUY_PLAN_BUTTON.format(
                        label=_plan_label(plan), price=plan.price_xtr
                    ),
                    callback_data=f"buy:plan:{plan.code}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_plans(message: Message) -> None:
    if not get_settings().billing_enabled:
        await message.answer(BUY_DISABLED)
        return
    try:
        async with ApiClient() as api:
            plans = await api.list_plans()
    except ApiError as exc:
        await message.answer(BUY_API_ERROR.format(message=exc.user_message))
        return
    if not plans:
        await message.answer(BUY_DISABLED)
        return
    await message.answer(BUY_PROMPT, reply_markup=_plans_kb(plans))


@router.message(Command("buy"))
async def buy_cmd(message: Message) -> None:
    await _show_plans(message)


@router.callback_query(F.data == "buy:start")
async def buy_callback(cb: CallbackQuery) -> None:
    resolved = resolve_cb(cb)
    if resolved is None:
        await cb.answer()
        return
    _user, message = resolved
    await _show_plans(message)
    await cb.answer()


@router.callback_query(F.data.startswith("buy:plan:"))
async def buy_plan(cb: CallbackQuery) -> None:
    if cb.data is None:
        await cb.answer()
        return
    plan_code = cb.data.removeprefix("buy:plan:")
    resolved = resolve_cb(cb)
    if resolved is None:
        await cb.answer()
        return
    user, message = resolved

    if not get_settings().billing_enabled:
        await message.answer(BUY_DISABLED)
        await cb.answer()
        return

    try:
        async with ApiClient() as api:
            draft = await api.create_order(tg_id=user.id, plan_code=plan_code)
    except ApiError as exc:
        if exc.code in ("invalid_plan", "billing_disabled"):
            await message.answer(BUY_PLAN_NOT_FOUND)
        else:
            await message.answer(BUY_API_ERROR.format(message=exc.user_message))
        await cb.answer()
        return

    label = BUY_PLAN_LABEL.get(plan_code, plan_code)
    bot = cb.bot
    if bot is None:
        await cb.answer()
        return
    await bot.send_invoice(
        chat_id=user.id,
        title=BUY_INVOICE_TITLE.format(label=label),
        description=BUY_INVOICE_DESCRIPTION.format(label=label),
        payload=draft.invoice_payload,
        provider_token="",  # Telegram Stars: empty provider token
        currency="XTR",
        prices=[LabeledPrice(label=label, amount=draft.amount_xtr)],
    )
    await cb.answer()


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    bot = query.bot
    if bot is None:
        return
    try:
        async with ApiClient() as api:
            ok = await api.precheck_order(
                invoice_payload=query.invoice_payload,
                amount_xtr=query.total_amount,
            )
    except ApiError as exc:
        log.warning(
            "purchase.precheck.api_error",
            code=exc.code,
            payload=query.invoice_payload,
        )
        await bot.answer_pre_checkout_query(
            query.id, ok=False, error_message=exc.user_message
        )
        return
    except Exception:  # noqa: BLE001
        log.exception("purchase.precheck.unexpected", payload=query.invoice_payload)
        await bot.answer_pre_checkout_query(
            query.id, ok=False, error_message="Внутренняя ошибка. Попробуй позже."
        )
        return

    if ok:
        await bot.answer_pre_checkout_query(query.id, ok=True)
    else:
        await bot.answer_pre_checkout_query(
            query.id, ok=False, error_message="Заказ недоступен."
        )


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    sp = message.successful_payment
    if sp is None or message.from_user is None:
        return
    try:
        async with ApiClient() as api:
            ack = await api.notify_payment_success(
                invoice_payload=sp.invoice_payload,
                amount_xtr=sp.total_amount,
                telegram_payment_charge_id=sp.telegram_payment_charge_id,
                provider_payment_charge_id=sp.provider_payment_charge_id or None,
            )
    except ApiError as exc:
        log.error(
            "purchase.success.api_error",
            code=exc.code,
            payload=sp.invoice_payload,
            tg_id=message.from_user.id,
        )
        await message.answer(PAYMENT_FAILED)
        return
    log.info(
        "purchase.success.ack",
        order_id=ack.order_id,
        subscription_id=ack.subscription_id,
        tg_id=message.from_user.id,
    )
    await message.answer(
        PAYMENT_SUCCESS.format(expires_at=ack.new_expires_at or "∞")
    )
