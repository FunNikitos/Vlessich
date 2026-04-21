"""Subscription display (TZ §7).

Shows current subscription state. If user has an active/trial sub and
``BOT_WEBAPP_URL`` is configured, sends a Mini-App button with the
``sub_token`` so the Mini-App can fetch the real sub URL via sub-Worker
(Stage 2).
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)

from app.config import get_settings
from app.handlers._utils import resolve_cb
from app.services.api_client import ApiClient, ApiError
from app.texts import SUBSCRIPTION_ACTIVE, SUBSCRIPTION_NONE

router = Router(name="subscription")


def _webapp_kb(sub_token: str) -> InlineKeyboardMarkup | None:
    settings = get_settings()
    if not settings.webapp_url:
        return None
    url = f"{str(settings.webapp_url).rstrip('/')}?token={sub_token}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📱 Открыть Mini-App",
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )


@router.callback_query(F.data == "sub:show")
async def show_subscription(cb: CallbackQuery) -> None:
    resolved = resolve_cb(cb)
    if resolved is None:
        await cb.answer()
        return
    user, message = resolved
    try:
        async with ApiClient() as api:
            sub = await api.get_subscription(tg_id=user.id)
    except ApiError as exc:
        await cb.answer(exc.user_message, show_alert=True)
        return

    if sub.status == "NONE" or sub.sub_token is None:
        await message.answer(SUBSCRIPTION_NONE)
        await cb.answer()
        return

    await message.answer(
        SUBSCRIPTION_ACTIVE.format(
            plan=sub.plan or "—",
            expires_at=sub.expires_at or "∞",
        ),
        reply_markup=_webapp_kb(sub.sub_token),
    )
    await cb.answer()
