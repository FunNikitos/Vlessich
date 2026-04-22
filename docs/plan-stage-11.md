# Stage 11 — Billing / Payments (Telegram Stars MVP)

Status: in_progress (branched off Stage 10 HEAD `9adbec1`).

## Goal

Закрыть revenue gap: дать юзеру купить подписку напрямую из бота
без активационного кода. MVP — **Telegram Stars only**, fixed SKU
`1m` / `3m` / `12m`, one-time purchase (no auto-renewal), refund —
admin-only manual.

## Locked decisions (user, начало сессии Stage 11)

- **Provider**: Telegram Stars only. `bot.send_invoice(..., provider_token='', currency='XTR', ...)`.
  Никаких внешних API ключей / KYC / merchant-аккаунтов.
- **Plans**: фиксированный набор `1m` / `3m` / `12m` (таблица `plans`,
  seed на startup, currency='XTR').
- **Auto-renewal**: OFF (Telegram Stars subscription API не используем
  в MVP). One-time purchase, manual renew. Reuse существующих
  reminders 24h/6h/1h.
- **Refund**: admin-only manual. `POST /admin/orders/{id}/refund`
  (superadmin) → API → Bot HMAC push → `bot.refund_star_payment(...)`
  + REVOKE подписки (если выдана этим order'ом).
- **Branch base**: `feat/stage-10-mtproto-rotation-broadcast` HEAD
  `9adbec1`.

## Architecture

```
        ┌──────────────── Bot (aiogram 3) ────────────────┐
user /buy ─▶│ purchase.py: list_plans → inline keyboard │
            │   ↓ user picks plan_code                   │
            │ api_client.create_order_draft(tg_id, code) │
            │   ↓ order_id (uuid hex)                    │
            │ bot.send_invoice(                          │
            │   chat_id, title, description,             │
            │   payload=order_id,                        │
            │   provider_token='', currency='XTR',       │
            │   prices=[LabeledPrice(label, amount_xtr)])│
            │                                            │
            │ @dp.pre_checkout_query()                   │
            │   → api_client.precheck_order(order_id)    │
            │   → answer_pre_checkout_query(ok=...)      │
            │                                            │
            │ @dp.message(F.successful_payment)          │
            │   → api_client.notify_payment_success(     │
            │       tg_id, order_id, telegram_charge_id, │
            │       provider_charge_id, amount_xtr)      │
            │   → DM "Спасибо! Подписка продлена…"       │
            └────────────────┬───────────────────────────┘
                             │ HTTP HMAC
                             ▼
        ┌──────────────── API (FastAPI) ──────────────────┐
        │ POST /internal/payments/create_order            │
        │   billing.create_order(tg_id, plan_code)        │
        │     - validate plan active                      │
        │     - cancel any stale PENDING (user)           │
        │     - INSERT orders(status='PENDING')           │
        │     - return order_id, amount_xtr               │
        │                                                 │
        │ POST /internal/payments/precheck                │
        │   billing.precheck(order_id)                    │
        │     - SELECT order WHERE status='PENDING'       │
        │     - return ok=true|false (+ reason)           │
        │                                                 │
        │ POST /internal/payments/success                 │
        │   billing.mark_paid(order_id, charge_ids,       │
        │                      amount_xtr)                │
        │     - tx: assert PENDING, amounts match         │
        │     - UPDATE orders SET status='PAID',          │
        │              telegram_charge_id, provider_…,    │
        │              paid_at=now()                      │
        │     - extend or issue subscription              │
        │     - audit 'order_paid'                        │
        │                                                 │
        │ Admin endpoints (JWT superadmin):               │
        │ GET  /admin/orders                              │
        │ GET  /admin/orders/{id}                         │
        │ POST /admin/orders/{id}/refund                  │
        │   billing.refund(order_id, admin_id)            │
        │     - assert status='PAID'                      │
        │     - HTTP HMAC push to Bot                     │
        │       /internal/refund/star_payment             │
        │     - on 200: UPDATE status='REFUNDED',         │
        │                refunded_at=now()                │
        │     - REVOKE subscription если последний order  │
        │     - audit 'order_refunded'                    │
        └─────────────────┬───────────────────────────────┘
                          │ HTTP HMAC (API → Bot)
                          ▼
        ┌──────────────── Bot /internal/refund/... ───────┐
        │ verify HMAC + ts skew                           │
        │ bot.refund_star_payment(                        │
        │   user_id=tg_id,                                │
        │   telegram_payment_charge_id=...                │
        │ )                                               │
        │ on success → 200 {ok: true}                     │
        │ on TelegramAPIError → 502 + log                 │
        └─────────────────────────────────────────────────┘
```

## Subscription extension semantics (`billing.mark_paid`)

Состояния пользователя в момент оплаты:

| Текущая `Subscription`              | Результат |
|---|---|
| Нет ACTIVE/TRIAL                     | Создать новую `ACTIVE`, `expires_at = now() + duration_days` |
| `TRIAL` (есть)                       | Превратить в `ACTIVE` (status=ACTIVE), `expires_at = max(expires_at, now()) + duration_days` |
| `ACTIVE` (есть, не истекла)          | Продлить: `expires_at += duration_days` |
| `EXPIRED` (есть, в прошлом)          | Reactivate: status=ACTIVE, `expires_at = now() + duration_days` |
| `REVOKED`                            | Создать новую `ACTIVE` (старая остаётся в истории) |

`Subscription.last_order_id` обновляется на каждой удачной оплате
(новая колонка, nullable FK на `orders.id`). При refund — REVOKE
только если `subscription.last_order_id == order.id` (т.е. этот order
дал текущий запас дней).

## Data flow / state machine

```
   ┌─────────────┐  user picks plan       ┌───────────┐
   │   (none)    │ ─────────────────────▶ │  PENDING  │
   └─────────────┘                        └─────┬─────┘
                                                │ successful_payment
                                                ▼
                                          ┌───────────┐
                                          │   PAID    │
                                          └─────┬─────┘
                                                │ admin refund
                                                ▼
                                          ┌───────────┐
                                          │ REFUNDED  │
                                          └───────────┘

   PENDING → FAILED — если pre_checkout вернул ok=false
                       (план stale, цена изменилась, и т.п.)
                       или user отменил invoice (TTL 1h, очистка
                       при следующем create_order того же user'а).
```

## Locked schema

```python
class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)  # "1m" | "3m" | "12m"
    duration_days: Mapped[int]
    price_xtr: Mapped[int]
    currency: Mapped[str] = mapped_column(String(8), default="XTR", server_default="XTR")
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','PAID','REFUNDED','FAILED')",
            name="ck_orders_status",
        ),
        Index(
            "ix_orders_one_pending_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index("ix_orders_user_created", "user_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.tg_id", ondelete="CASCADE"))
    plan_code: Mapped[str] = mapped_column(String(16))
    amount_xtr: Mapped[int]
    currency: Mapped[str] = mapped_column(String(8), default="XTR", server_default="XTR")
    status: Mapped[str] = mapped_column(String(16), default="PENDING", server_default="PENDING")
    invoice_payload: Mapped[str] = mapped_column(Text)  # = order_id.hex
    telegram_payment_charge_id: Mapped[Optional[str]] = mapped_column(String(255))
    provider_payment_charge_id: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    paid_at: Mapped[Optional[datetime]]
    refunded_at: Mapped[Optional[datetime]]
    refunded_by_admin_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admins.id"))
```

`subscriptions` add columns (alembic alter):
- `last_order_id UUID NULL FK → orders.id ON DELETE SET NULL` (nullable;
  для history — если в будущем понадобится отвязать).

Seed (idempotent, on API startup):
```python
DEFAULT_PLANS = [
    ("1m", 30, 100),
    ("3m", 90, 250),
    ("12m", 365, 900),
]
```

> Цены — **placeholder**. Реальные цены конфигурируются через alter
> rows / отдельную миграцию data-only при tuning. Seed только если
> запись отсутствует (NOT update).

## Locked settings (env `API_*`)

| Env | Default | Назначение |
|---|---|---|
| `API_BILLING_ENABLED` | `false` | Master flag для всех billing endpoints + bot /buy menu |
| `API_BILLING_PLAN_TTL_PENDING_SEC` | `3600` | TTL для PENDING orders (cleanup на create_order того же user'а) |
| `API_BILLING_REFUND_BOT_NOTIFY_URL` | `""` | URL bot endpoint `/internal/refund/star_payment` (HMAC) |

Bot side (env `BOT_*`):

| Env | Default | Назначение |
|---|---|---|
| `BOT_BILLING_ENABLED` | `false` | Master flag для /buy menu в боте |
| `BOT_INTERNAL_REFUND_PATH` | `/internal/refund/star_payment` | Path на notify_server (порт 8081) |

## Audit & metrics

AuditLog actions (новые):
- `order_created` — actor_type='user', target_id=order_id, payload `{plan_code, amount_xtr}`.
- `order_paid` — actor_type='user', target_id=order_id, payload `{plan_code, amount_xtr, telegram_charge_id_sha256}`.
- `order_refunded` — actor_type='admin', target_id=order_id, payload `{plan_code, amount_xtr, subscription_revoked: bool}`.

> `telegram_payment_charge_id` хранится **plaintext** в таблице
> `orders` (не PII по строгому определению, нужен для refund API).
> В AuditLog payload — `sha256(...)` чтобы не дублировать.

Prometheus (новые в `app.metrics`):
- `vlessich_orders_total{status, plan}` Counter — created|paid|refunded|failed × 1m/3m/12m.
- `vlessich_revenue_xtr_total{plan}` Counter — суммарный XTR по PAID per-plan.
- `vlessich_refunds_total{plan}` Counter.

Alert rules (`infra/prometheus/rules/vlessich.yml`):
- `OrderFailureSpike` — `rate(vlessich_orders_total{status="failed"}[15m]) > 0.1` for 10m (warning).
- `RefundVolumeHigh` — `rate(vlessich_refunds_total[1h]) > 0.05` for 1h (warning, possible abuse).

## Error codes (новые в `ApiCode`)

- `BILLING_DISABLED` = `"billing_disabled"` — master flag off.
- `INVALID_PLAN` = `"invalid_plan"` — plan_code unknown / inactive.
- `ORDER_NOT_FOUND` = `"order_not_found"` — order_id неизвестен.
- `ORDER_NOT_PENDING` = `"order_not_pending"` — pre_checkout / mark_paid на не-PENDING.
- `ORDER_NOT_PAID` = `"order_not_paid"` — refund на не-PAID.
- `ORDER_ALREADY_REFUNDED` = `"order_already_refunded"` — повторный refund.
- `PAYMENT_AMOUNT_MISMATCH` = `"payment_amount_mismatch"` — total_amount ≠ orders.amount_xtr.
- `PAYMENT_VERIFICATION_FAILED` = `"payment_verification_failed"` — refund bot endpoint вернул не-2xx.

## Rollout / rollback

**Rollout**:
1. Deploy с `API_BILLING_ENABLED=false`, `BOT_BILLING_ENABLED=false`.
2. Применить миграцию 0006 (создать `plans`, `orders`, alter `subscriptions`).
3. На startup API выполнится `seed_default_plans()` (idempotent, NOT update).
4. Smoke-test в staging: вручную INSERT order, имитировать
   `successful_payment` через mock — проверить mark_paid.
5. Включить `BOT_BILLING_ENABLED=true`, `API_BILLING_ENABLED=true`
   одновременно (bot покажет /buy menu, API начнёт принимать invoices).
6. Через 24h без incidents — open для prod.

**Rollback**: вернуть оба flags в `false`. Bot скрывает /buy, API
отвечает `BILLING_DISABLED` на all billing endpoints (uncluding
admin refund — refund остаётся доступен, чтобы можно было
вернуть деньги при rollback). Migration не откатываем (идемпотентна).

## Commits T1..T12

- **T1** (this) — `docs/plan-stage-11.md`.
- **T2** — settings (`BILLING_*`) + ApiCode entries.
- **T3** — alembic 0006: `plans` + `orders` + alter `subscriptions.last_order_id`.
- **T4** — models `Plan`, `Order` + `Subscription.last_order_id` mapping.
- **T5** — `services/billing.py`: `list_active_plans`, `create_order`,
  `precheck`, `mark_paid`, `refund`, `seed_default_plans`.
- **T6** — `routers/internal/payments.py`: 3 endpoints
  (create_order / precheck / success), HMAC + ApiCode wiring.
- **T7** — `routers/admin/orders.py`: GET list / GET {id} / POST refund.
- **T8** — bot `bot/app/handlers/purchase.py`: /buy + plan keyboard +
  pre_checkout + successful_payment; `texts.py` purchase strings;
  api_client новые методы.
- **T9** — bot `notify_server.py`: добавить `/internal/refund/star_payment`
  endpoint (HMAC + `bot.refund_star_payment`).
- **T10** — `docker-compose.dev.yml` env updates; `.env.example`
  (api + bot); metrics + alerts; seed на startup wired в `app.main`.
- **T11** — tests: billing service unit (state machine, sub extension,
  refund), admin orders, bot purchase smoke (handler signatures + texts).
- **T12** — docs: ARCHITECTURE §23, CHANGELOG `[0.11.0]`,
  README updates (root + bot/api), DoD checklist.

## Verification per commit

```powershell
python -c "import ast,glob; [ast.parse(open(f,encoding='utf-8').read(),f) for f in glob.glob('api/**/*.py', recursive=True)+glob.glob('bot/**/*.py', recursive=True)]; print('OK')"
python -c "import yaml,json; yaml.safe_load(open('infra/prometheus/rules/vlessich.yml',encoding='utf-8')); yaml.safe_load(open('docker-compose.dev.yml',encoding='utf-8')); json.load(open('infra/grafana/dashboards/vlessich.json',encoding='utf-8')); print('OK')"
Get-ChildItem api\app,api\tests,bot\app,bot\tests -Recurse -Include *.py | Select-String -Pattern '# type: ignore'
```

Pre-existing type-escapes (исключать в audit):
- `api/tests/test_captcha.py:38` — `# type: ignore[no-untyped-def]` (Stage 6).
- `bot/app/handlers/_utils.py:4` — `# type: ignore` (aiogram typing).

## Out-of-scope (deferred)

- **Auto-renewal** через Telegram Stars subscriptions API (xtr-subs) —
  требует отдельной state-machine + webhook/recurring API.
- **Self-serve refund** в боте — UX risk (abuse), оставлено admin-only.
- **Promo-codes / discounts** — отдельная фича (Plan + Promo cross-table).
- **Multi-currency** — currency hard-coded `XTR` в seed; колонка
  оставлена для будущего multi-provider.
- **Receipts / счета** — Telegram сам отправляет fiscal receipt через Stars.
- **Admin UI orders page** — backend endpoints готовы; React-страница в
  `admin/` отдельным Stage (UX polish).
- **Webhook re-delivery / dead-letter** для `successful_payment` —
  Telegram сам ретраит через `pre_checkout_query` lifecycle; idempotency
  обеспечивается уникальностью `telegram_payment_charge_id` (not
  enforced как UNIQUE constraint в MVP, проверка в `mark_paid`).
