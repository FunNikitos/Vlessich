"""MTProto proxy issuance (TZ §9A)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.handlers._utils import resolve_cb
from app.services.api_client import ApiClient, ApiError
from app.texts import MTPROTO_BLOCK

router = Router(name="mtproto")


@router.callback_query(F.data == "mtproto:get")
async def get_mtproto(cb: CallbackQuery) -> None:
    resolved = resolve_cb(cb)
    if resolved is None:
        await cb.answer()
        return
    user, message = resolved
    try:
        async with ApiClient() as api:
            mp = await api.get_mtproto(tg_id=user.id)
    except ApiError as exc:
        await cb.answer(exc.user_message, show_alert=True)
        return
    await message.answer(
        MTPROTO_BLOCK.format(deeplink=mp.tg_deeplink, host=mp.host, port=mp.port)
    )
    await cb.answer()
