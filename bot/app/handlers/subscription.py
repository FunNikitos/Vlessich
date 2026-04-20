"""Subscription display & copy (TZ §7, §8.4)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.services.api_client import ApiClient, ApiError
from app.texts import SUBSCRIPTION_BLOCK

router = Router(name="subscription")


@router.callback_query(F.data == "sub:show")
async def show_subscription(cb: CallbackQuery) -> None:
    if cb.from_user is None:
        await cb.answer()
        return
    try:
        async with ApiClient() as api:
            sub = await api.get_subscription(tg_id=cb.from_user.id)
    except ApiError as exc:
        await cb.answer(exc.user_message, show_alert=True)
        return
    if cb.message:
        await cb.message.answer(  # type: ignore[union-attr]
            SUBSCRIPTION_BLOCK.format(
                sub_url=sub.sub_url,
                expires_at=sub.expires_at or "∞",
                plan=sub.plan,
            )
        )
    await cb.answer()
