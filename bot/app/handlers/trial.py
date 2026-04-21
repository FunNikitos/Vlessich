"""Trial flow (TZ §4.1).

Two-step: user taps «🆓 Триал» -> we request a contact via
ReplyKeyboardMarkup(request_contact=True). On receiving the contact we
verify ``contact.user_id == from_user.id`` (prevents passing someone
else's contact) and POST to ``/internal/trials`` with referral_source
pulled from the deep-link cache.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from redis.asyncio import Redis

from app.handlers._utils import resolve_cb
from app.services.api_client import ApiClient, ApiError
from app.services.deeplink import consume_deeplink, drop_deeplink
from app.texts import (
    TRIAL_ALREADY,
    TRIAL_CREATED,
    TRIAL_PHONE_BAD_OWNER,
    TRIAL_PHONE_REQUEST,
)

router = Router(name="trial")


def _phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


@router.callback_query(F.data == "trial:start")
async def trial_start(cb: CallbackQuery) -> None:
    resolved = resolve_cb(cb)
    if resolved is None:
        await cb.answer()
        return
    _user, message = resolved
    await message.answer(TRIAL_PHONE_REQUEST, reply_markup=_phone_kb())
    await cb.answer()


@router.message(F.contact)
async def on_contact(message: Message, redis: Redis) -> None:
    if message.from_user is None or message.contact is None:
        return
    # Защита: пользователь должен поделиться именно СВОИМ контактом.
    if message.contact.user_id != message.from_user.id:
        await message.answer(TRIAL_PHONE_BAD_OWNER, reply_markup=ReplyKeyboardRemove())
        return
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    referral_source = await consume_deeplink(redis, message.from_user.id)
    try:
        async with ApiClient() as api:
            sub = await api.create_trial(
                tg_id=message.from_user.id,
                phone_e164=phone,
                referral_source=referral_source,
            )
    except ApiError as exc:
        text = TRIAL_ALREADY if exc.code == "trial_already_used" else f"⚠️ {exc.user_message}"
        await message.answer(text, reply_markup=ReplyKeyboardRemove())
        return
    await drop_deeplink(redis, message.from_user.id)
    await message.answer(
        TRIAL_CREATED.format(expires_at=sub.expires_at or "∞"),
        reply_markup=ReplyKeyboardRemove(),
    )
