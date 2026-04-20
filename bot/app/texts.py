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
    "Отправь код в формате <code>XXXX-XXXX-XXXX</code>.\n"
    "Регистр не важен."
)

ACTIVATE_BAD_CODE = (
    "Неверный формат. Ожидается <code>XXXX-XXXX-XXXX</code>."
)

ACTIVATE_OK = (
    "✅ Код активирован.\n"
    "Действует до: <b>{expires_at}</b>.\n\n"
    "Нажми «Показать подписку» — пришлю ссылку и QR."
)

TRIAL_CREATED = "🎁 Триал активирован до <b>{expires_at}</b>."
TRIAL_ALREADY = "Триал уже использован ранее."

SUBSCRIPTION_BLOCK = (
    "🔗 Подписка\n"
    "<code>{sub_url}</code>\n\n"
    "План: <b>{plan}</b>\n"
    "До: <b>{expires_at}</b>"
)

MTPROTO_BLOCK = (
    "📡 MTProto для Telegram\n"
    "Нажми, чтобы добавить: {deeplink}\n\n"
    "Хост: <code>{host}</code>\n"
    "Порт: <code>{port}</code>"
)
