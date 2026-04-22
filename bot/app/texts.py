"""UI strings (RU). Centralized for easy review and future i18n."""
from __future__ import annotations

START_TEXT = (
    "<b>Vlessich</b> — приватный VPN для РФ.\n\n"
    "• Активируй код или получи <b>3-дневный триал</b>.\n"
    "• Поддержка iOS / Android / Windows / macOS.\n"
    "• Отдельный MTProto для Telegram.\n"
)

HELP_TEXT = (
    "Команды:\n"
    "/start — главное меню\n"
    "/activate — ввести код\n"
    "/help — эта справка\n"
)

ACTIVATE_PROMPT = (
    "Отправь код. Регистр и дефисы не важны."
)

ACTIVATE_BAD_CODE = (
    "Неверный формат кода. Допустимы латинские буквы и цифры."
)

ACTIVATE_OK = (
    "✅ Код активирован.\n"
    "Действует до: <b>{expires_at}</b>.\n\n"
    "Нажми «💳 Показать подписку» — пришлю ссылку для приложения."
)

TRIAL_PHONE_REQUEST = (
    "Чтобы выдать триал, поделись номером телефона кнопкой ниже.\n"
    "Это нужно для защиты от злоупотреблений (1 триал на номер)."
)

TRIAL_PHONE_BAD_OWNER = (
    "Можно поделиться только своим контактом."
)

TRIAL_CREATED = "🎁 Триал активирован до <b>{expires_at}</b>."
TRIAL_ALREADY = "Триал уже использован ранее."

SUBSCRIPTION_NONE = (
    "У тебя пока нет активной подписки.\n"
    "Активируй код или получи триал из главного меню."
)

SUBSCRIPTION_ACTIVE = (
    "🔗 Подписка активна\n"
    "План: <b>{plan}</b>\n"
    "До: <b>{expires_at}</b>\n\n"
    "Открой Mini-App, чтобы получить ссылку для приложения."
)

MTPROTO_BLOCK = (
    "📡 MTProto для Telegram\n"
    "Нажми, чтобы добавить: {deeplink}\n\n"
    "Хост: <code>{host}</code>\n"
    "Порт: <code>{port}</code>"
)

MTPROTO_ROTATED = (
    "🔄 MTProto-прокси обновлён\n\n"
    "Мы обновили секрет. Добавь новый прокси в Telegram:\n"
    "{deeplink}\n\n"
    "Хост: <code>{host}</code>\n"
    "Порт: <code>{port}</code>"
)

# Stage 11 — Billing / Telegram Stars
BUY_DISABLED = (
    "Платежи временно отключены. Попробуй позже или свяжись с поддержкой."
)

BUY_PROMPT = (
    "💎 Оплата через Telegram Stars\n\n"
    "Выбери срок подписки:"
)

BUY_PLAN_LABEL = {
    "1m": "1 месяц",
    "3m": "3 месяца",
    "12m": "12 месяцев",
}

BUY_PLAN_BUTTON = "{label} — {price} ⭐"

BUY_INVOICE_TITLE = "Vlessich VPN — {label}"
BUY_INVOICE_DESCRIPTION = (
    "Подписка на {label}. Оплата через Telegram Stars (⭐). "
    "После оплаты подписка активируется автоматически."
)

BUY_PLAN_NOT_FOUND = "Тариф недоступен. Попробуй ещё раз."
BUY_API_ERROR = "Не удалось создать заказ: {message}"

PAYMENT_SUCCESS = (
    "✅ Платёж прошёл — спасибо!\n\n"
    "Подписка активна до <b>{expires_at}</b>.\n"
    "Открой Mini-App или нажми «💳 Показать подписку» для деталей."
)

PAYMENT_FAILED = (
    "⚠️ Платёж не подтверждён. Если со счёта списаны звёзды — напиши в поддержку."
)

REFUND_NOTICE = (
    "↩️ Возврат\n\n"
    "Платёж возвращён администратором. Звёзды вернутся на твой счёт. "
    "Если подписка отозвана — оформи новую через /buy."
)
