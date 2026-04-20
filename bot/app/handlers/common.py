"""Common handlers: /start, /help, fallback."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from app.config import get_settings
from app.texts import HELP_TEXT, START_TEXT

router = Router(name="common")


def _main_kb() -> InlineKeyboardMarkup:
    settings = get_settings()
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🎟 Активировать код", callback_data="activate:start")],
        [InlineKeyboardButton(text="🆓 Триал на 3 дня", callback_data="trial:start")],
    ]
    if settings.webapp_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📱 Открыть Mini-App",
                    web_app=WebAppInfo(url=str(settings.webapp_url)),
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="📡 MTProto для Telegram", callback_data="mtproto:get")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    await message.answer(START_TEXT, reply_markup=_main_kb())


@router.message(Command("help"))
async def on_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(F.text)
async def on_unknown(message: Message) -> None:
    # Не эхо-бот; молча игнорируем посторонний текст вне FSM (см. activation handler).
    await message.answer(
        "Команды: /start, /help.\nИспользуй кнопки ниже.",
        reply_markup=_main_kb(),
    )
