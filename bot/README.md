# Vlessich — Telegram bot (aiogram 3)

Python 3.12 · aiogram 3 · pydantic v2 · Redis FSM · structlog.

## Dev

```bash
cp .env.example .env.dev
# заполнить BOT_TOKEN и BOT_API_INTERNAL_SECRET
pip install -e ".[dev]"
python -m app
```

## Prod (webhook)

Задать `BOT_WEBHOOK_URL` + `BOT_WEBHOOK_SECRET`. Запуск автоматически
переключится в webhook-режим (aiohttp на `0.0.0.0:8080`).

## Структура

```
app/
  main.py          — bootstrap + webhook/polling mode
  config.py        — pydantic-settings (BOT_* env vars)
  logging.py       — structlog JSON
  handlers/        — aiogram routers (common, activation, subscription, mtproto)
  middlewares/     — throttling
  services/        — HTTP-клиент к backend API (HMAC-signed)
  texts.py         — UI-строки (RU, подготовлено к i18n)
tests/             — smoke-тесты wiring
```

См. `TZ.md §3, §5, §9A` для flows.
