"""Activation flow (TZ §5).

FSM: prompt for code, validate format locally (alphanumeric, 8–32 chars),
send to backend with referral_source pulled from Redis deep-link cache.
"""
from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis

from app.handlers._utils import resolve_cb
from app.services.api_client import ApiClient, ApiError
from app.services.deeplink import consume_deeplink, drop_deeplink
from app.texts import ACTIVATE_BAD_CODE, ACTIVATE_OK, ACTIVATE_PROMPT

router = Router(name="activation")

CODE_RE = re.compile(r"^[A-Z0-9-]{4,32}$")


class ActivateFSM(StatesGroup):
    waiting_code = State()


@router.callback_query(F.data == "activate:start")
async def activate_start(cb: CallbackQuery, state: FSMContext) -> None:
    resolved = resolve_cb(cb)
    if resolved is None:
        await cb.answer()
        return
    _user, message = resolved
    await state.set_state(ActivateFSM.waiting_code)
    await message.answer(ACTIVATE_PROMPT)
    await cb.answer()


@router.message(Command("activate"))
async def activate_cmd(message: Message, state: FSMContext) -> None:
    await state.set_state(ActivateFSM.waiting_code)
    await message.answer(ACTIVATE_PROMPT)


@router.message(ActivateFSM.waiting_code, F.text)
async def activate_code(message: Message, state: FSMContext, redis: Redis) -> None:
    raw = (message.text or "").strip().upper().replace(" ", "")
    if not CODE_RE.match(raw):
        await message.answer(ACTIVATE_BAD_CODE)
        return
    if message.from_user is None:
        return
    referral_source = await consume_deeplink(redis, message.from_user.id)
    try:
        async with ApiClient() as api:
            sub = await api.activate_code(
                tg_id=message.from_user.id,
                code=raw,
                referral_source=referral_source,
            )
    except ApiError as exc:
        await message.answer(f"⚠️ {exc.user_message}")
        return
    await state.clear()
    await drop_deeplink(redis, message.from_user.id)
    await message.answer(ACTIVATE_OK.format(expires_at=sub.expires_at or "∞"))
