"""Routing-profile selector flow (Stage 12).

Entry points:

* ``/config`` command → renders the 4-profile inline keyboard.
* ``cfg:start`` callback (main menu button) → same.
* ``cfg:set:<profile>`` callback → calls ``ApiClient.set_routing_profile``
  and replies with the deep-link to the user's sub-Worker token in both
  sing-box and clash formats.

Master flag ``BOT_SMART_ROUTING_ENABLED`` short-circuits all entry
points to ``CONFIG_DISABLED``. Profile is one of the four locked names
``full|smart|adblock|plain``; anything else is rejected by the API
(``invalid_routing_profile``) so the bot just surfaces the message.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.config import get_settings
from app.handlers._utils import resolve_cb
from app.logging import log
from app.services.api_client import ApiClient, ApiError
from app.texts import (
    CONFIG_API_ERROR,
    CONFIG_DISABLED,
    CONFIG_NO_SUB,
    CONFIG_PROFILE_LABEL,
    CONFIG_PROFILE_SET,
    CONFIG_PROFILE_SET_NO_LINK,
    CONFIG_PROMPT,
)

router = Router(name="config")

PROFILES: tuple[str, ...] = ("full", "smart", "adblock", "plain")


def _profiles_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code in PROFILES:
        rows.append(
            [
                InlineKeyboardButton(
                    text=CONFIG_PROFILE_LABEL[code],
                    callback_data=f"cfg:set:{code}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_prompt(message: Message) -> None:
    if not get_settings().smart_routing_enabled:
        await message.answer(CONFIG_DISABLED)
        return
    await message.answer(CONFIG_PROMPT, reply_markup=_profiles_kb())


@router.message(Command("config"))
async def config_cmd(message: Message) -> None:
    await _show_prompt(message)


@router.callback_query(F.data == "cfg:start")
async def config_callback(cb: CallbackQuery) -> None:
    resolved = resolve_cb(cb)
    if resolved is None:
        await cb.answer()
        return
    _user, message = resolved
    await _show_prompt(message)
    await cb.answer()


def _format_links(sub_token: str | None) -> tuple[str | None, str | None]:
    settings = get_settings()
    base = settings.sub_worker_base_url
    if base is None or sub_token is None:
        return None, None
    base_str = str(base).rstrip("/")
    return (
        f"{base_str}/{sub_token}?fmt=singbox",
        f"{base_str}/{sub_token}?fmt=clash",
    )


@router.callback_query(F.data.startswith("cfg:set:"))
async def config_set(cb: CallbackQuery) -> None:
    if cb.data is None:
        await cb.answer()
        return
    profile = cb.data.removeprefix("cfg:set:")
    if profile not in PROFILES:
        await cb.answer()
        return
    resolved = resolve_cb(cb)
    if resolved is None:
        await cb.answer()
        return
    user, message = resolved

    if not get_settings().smart_routing_enabled:
        await message.answer(CONFIG_DISABLED)
        await cb.answer()
        return

    try:
        async with ApiClient() as api:
            ack = await api.set_routing_profile(tg_id=user.id, profile=profile)
            sub = await api.get_subscription(tg_id=user.id)
    except ApiError as exc:
        if exc.code in ("no_active_subscription", "user_not_found"):
            await message.answer(CONFIG_NO_SUB)
        else:
            await message.answer(CONFIG_API_ERROR.format(message=exc.user_message))
        await cb.answer()
        return

    label = CONFIG_PROFILE_LABEL.get(ack.profile, ack.profile)
    singbox_url, clash_url = _format_links(sub.sub_token)
    if singbox_url is not None and clash_url is not None:
        await message.answer(
            CONFIG_PROFILE_SET.format(
                label=label, singbox_url=singbox_url, clash_url=clash_url
            )
        )
    else:
        await message.answer(CONFIG_PROFILE_SET_NO_LINK.format(label=label))
    log.info(
        "config.profile.set",
        tg_id=user.id,
        profile=ack.profile,
        subscription_id=ack.subscription_id,
    )
    await cb.answer()
