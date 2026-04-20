"""Activation flow (TZ §5).

FSM stub: waits for activation code, validates against backend, then shows
subscription. Real validation delegated to API client.
"""
from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.handlers._utils import resolve_cb
from app.services.api_client import ApiClient, ApiError
from app.texts import (
    ACTIVATE_BAD_CODE,
    ACTIVATE_OK,
    ACTIVATE_PROMPT,
    TRIAL_ALREADY,
    TRIAL_CREATED,
)

router = Router(name="activation")

CODE_RE = re.compile(r"^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")


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
async def activate_code(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().upper().replace(" ", "")
    if not CODE_RE.match(raw):
        await message.answer(ACTIVATE_BAD_CODE)
        return
    if message.from_user is None:
        return
    try:
        async with ApiClient() as api:
            sub = await api.activate_code(tg_id=message.from_user.id, code=raw)
    except ApiError as exc:
        await message.answer(f"⚠️ {exc.user_message}")
        return
    await state.clear()
    await message.answer(ACTIVATE_OK.format(expires_at=sub.expires_at or "∞"))


@router.callback_query(F.data == "trial:start")
async def trial_start(cb: CallbackQuery) -> None:
    resolved = resolve_cb(cb)
    if resolved is None:
        await cb.answer()
        return
    user, message = resolved
    try:
        async with ApiClient() as api:
            res = await api.create_trial(tg_id=user.id)
    except ApiError as exc:
        await cb.answer(exc.user_message, show_alert=True)
        return
    text = TRIAL_CREATED if res.created else TRIAL_ALREADY
    await message.answer(text.format(expires_at=res.expires_at))
    await cb.answer()
