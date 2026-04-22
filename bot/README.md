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
  handlers/        — aiogram routers (common, activation, subscription, mtproto, purchase)
  middlewares/     — throttling
  services/        — HTTP-клиент к backend API (HMAC-signed)
  notify_server.py — aiohttp app (MTProto rotated notify + Stars refund endpoint)
  texts.py         — UI-строки (RU, подготовлено к i18n)
```

См. `TZ.md §3, §5, §9A` и `docs/ARCHITECTURE.md §22/§23` для flows.

## Settings (Stage 11 billing)

| Env | Default | Назначение |
|---|---|---|
| `BOT_BILLING_ENABLED` | `false` | Master flag для /buy + кнопки «💎 Купить подписку». Off → пользователь видит `BUY_DISABLED`. |
| `BOT_INTERNAL_REFUND_PATH` | `/internal/refund/star_payment` | Endpoint в notify_server для API → bot refund push (HMAC, общий секрет `BOT_API_INTERNAL_SECRET`). Вызывает `bot.refund_star_payment(user_id, telegram_payment_charge_id)`. |

## Purchase flow (Telegram Stars)

1. `/buy` или callback `buy:start` → `api.list_plans()` → inline
   клавиатура с SKU (1m / 3m / 12m).
2. Выбор плана → `api.create_order(tg_id, plan_code)` → PENDING order
   → `bot.send_invoice(provider_token='', currency='XTR',
   prices=[LabeledPrice(amount=price_xtr)])`.
3. Telegram → `pre_checkout_query` → `api.precheck_order(...)` →
   `answer_pre_checkout_query(ok=True/False)`.
4. Telegram → `F.successful_payment` → `api.notify_payment_success(...)` →
   ответ с новой датой окончания.

Refund: API делает HMAC POST на `/internal/refund/star_payment`;
handler вызывает `bot.refund_star_payment(...)` и DM'ит
`REFUND_NOTICE` пользователю.

## Smart-routing / `/config` (Stage 12)

| Env | Default | Назначение |
|---|---|---|
| `BOT_SMART_ROUTING_ENABLED` | `false` | Master flag для `/config` + кнопки «📥 Получить конфиг». Off → handler/кнопка скрыты. |
| `BOT_SUB_WORKER_BASE_URL` | — | Public sub-Worker base URL. Bot конкатенирует с `Subscription.sub_url_token` для DM-deeplink'а. |

### Flow

1. `/config` или кнопка «📥 Получить конфиг» в главном меню.
2. Inline keyboard: **Full · Smart · AdBlock · Plain**.
3. Callback `cfg:set:<profile>` → `api.set_routing_profile(tg_id, profile)`
   (HMAC `POST /internal/smart_routing/set_profile`).
4. На `200 OK` бот DM'ит:
   * текущий профиль (label + краткое описание),
   * sub-Worker URL = `{BOT_SUB_WORKER_BASE_URL}/{sub_url_token}`,
   * напоминание: vless-клиент сам подтянет ruleset через
     `/internal/smart_routing/config` (singbox + clash формат).

Профили: `full` (RU direct + proxy others + ads block, DoD TZ §16),
`smart` (RU direct + proxy), `adblock` (всё direct + ads block,
TZ §18.6 DNS-only), `plain` (Stage 2 baseline, всё через VPN).
См. `docs/ARCHITECTURE.md §24`.
