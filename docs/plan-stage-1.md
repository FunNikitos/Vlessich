# Stage 1 — Backend + Bot MVP

**Версия:** 1.0
**Дата:** 20.04.2026
**Статус:** ⏳ pending approval (зависит от Stage 0 merge)
**Срок:** ~12-16 часов работы.
**Предпосылка:** Stage 0 смержен (миграции, crypto, Redis throttling).

## Утверждённые решения (locked)

- **Reminders runtime** = отдельный контейнер `reminders` в compose, образ
  api, CMD `python -m app.workers.reminders`. Использует `aiogram.Bot(token)`
  в send-only режиме (без polling). Токен бота через env, тот же что и
  у бот-сервиса. Преимущества: нет HTTP-hop, переживает падение бота,
  проще scaling.
- **Capture deep-link payload** = БЕЗ отдельного endpoint. Поле
  `referral_source: str | None` добавляется в request body
  `/internal/trials` и `/internal/codes/activate`. Бот при `/start <payload>`
  кэширует payload в Redis `dl:{tg_id}` (TTL 7 дней) и подставляет в
  первый mutating вызов. После использования — удаляет ключ.

---

## 0. Контекст

ТЗ §4 (потоки активации), §5 (admin codes), §5.5 (anti-abuse), §12 (БД),
§14 (audit log). Цель этапа — реализовать **реальную** бизнес-логику
активации/триала/выдачи подписки и MTProto, заменив stub-эндпоинты
API и дореализовав bot handlers. Remnawave интеграция — **mock-клиент**
за интерфейсом (реальный провижининг — Stage 2). Sub URL и sub-Worker —
**Stage 2**.

**Что НЕ делаем в этом этапе:**
- Cloudflare Worker `subscription.js` деплой (Stage 2).
- Реальный Remnawave API (только интерфейс + mock).
- Admin panel backend (Stage 3).
- Mini-App визуал (Stage 4).
- Reminders прод-режим на FI-ноде (только dev worker).
- Ротация IP / node health (Stage 5).

---

## 1. Definition of Done

- [ ] `/internal/codes/activate` реально активирует код в БД в транзакции:
      валидация, resolve, продление/замена подписки, инвариант 1 active/user,
      запись `audit_log` и `code_attempts`.
- [ ] `/internal/trials` реально создаёт триал: fingerprint check, 1 на
      `tg_id`, создаёт `subscription` (status=TRIAL), audit log.
- [ ] `/internal/users/{tg_id}/subscription` возвращает реальное состояние
      из БД (`NONE|ACTIVE|EXPIRED|TRIAL`) с `expires_at`, `plan`, `sub_token`.
- [ ] `/internal/mtproto/issue` выдаёт shared или per-user секрет из пула
      `mtproto_secrets`, фиксирует выдачу в audit log.
- [ ] HMAC-middleware на всех `/internal/*` проверяет `x-vlessich-sig`
      (SHA-256, clock-skew ≤60s). Запрос без подписи → 401.
- [ ] Bot handlers:
  - `/start <payload>` — capture deep-link (`ref_*`, `utm_*`), сохраняет
    в `users.referral_source`.
  - «Активировать код» → state `AWAITING_CODE` → текст кода → POST к
    `/internal/codes/activate` → ответ/ошибка с RU-текстами.
  - «Получить триал» → share-phone flow (Telegram Contact button) → POST
    к `/internal/trials` → выдача.
  - «Показать подписку» → GET `/internal/users/.../subscription` → Mini-App
    кнопка (`web_app` URL с `?token=<sub_token>`).
  - MTProto «Получить прокси» → `/internal/mtproto/issue` → отправка
    tg://proxy ссылки.
- [ ] Anti-abuse:
  - Redis rate-limit `/activate` = 5/10мин/tg_id, превышение → bot отвечает
    "слишком много попыток, подожди 10 минут".
  - Fingerprint triala = `sha256(phone_e164 + tg_id + FP_SALT)`; повтор →
    отказ с текстом.
- [ ] Reminders worker (arq): cron каждые 15 мин, проверяет subscriptions
      с `expires_at - now in [24h, 6h, 1h]` без соответствующей записи в
      `reminder_log`, отправляет через bot-клиент.
- [ ] Remnawave интерфейс:
  - `api/app/services/remnawave.py` с ABC `RemnawaveClient` и реализацией
    `MockRemnawaveClient` (in-memory).
  - DI через FastAPI dependency (prod заменит на HTTP-клиент в Stage 2).
- [ ] pytest coverage ≥80% на `api/app/routers/`, `api/app/services/`,
      `bot/app/handlers/`.
- [ ] Все сценарии из ТЗ §4.1-§4.6 покрыты интеграционными тестами
      (pytest + httpx + pytest-asyncio + aiogram test utils).
- [ ] Audit log записи присутствуют для: trial_issued, code_activated,
      code_attempt_failed, subscription_extended, subscription_replaced,
      mtproto_issued.
- [ ] Нет `# type: ignore`, `as any`, пустых `except:`.
- [ ] CHANGELOG обновлён.

---

## 2. Задачи (атомарные)

### T1 — HMAC middleware для `/internal/*`

**Что:**
- `api/app/security.py`: функция `verify_signature(body: bytes, sig: str, ts: str) -> None`:
  - считает `hmac.new(settings.internal_secret, f"{ts}.{body_sha256}", sha256)`;
  - сравнивает constant-time;
  - отклоняет если `abs(now - ts) > 60s`.
- FastAPI dependency `require_internal_hmac` — подключить ко всем `/internal/*` роутерам.
- Bot: `api_client.py` уже содержит подпись — сверить алгоритм (хеш тела +
  timestamp), поправить при расхождениях.

**Проверка:** unit-тесты (valid/invalid sig/old ts), интеграционный через httpx.

**Commit:** `feat(api): hmac signature verification for internal endpoints`
**Effort:** 45 мин.

---

### T2 — Remnawave interface + Mock client

**Что:**
- `api/app/services/remnawave.py`:
  ```python
  class RemnawaveClient(abc.ABC):
      async def create_user(self, subscription_id: UUID, plan: str, ttl_days: int) -> RemnaUser: ...
      async def extend_user(self, remna_user_id: str, ttl_days: int) -> None: ...
      async def revoke_user(self, remna_user_id: str) -> None: ...
      async def get_subscription_url(self, remna_user_id: str) -> str: ...
  ```
- `MockRemnawaveClient` — in-memory dict, возвращает детерминированные
  `sub_token` (hex 32).
- DI: `def get_remnawave() -> RemnawaveClient` — в Stage 2 заменится.
- Unit-тесты на mock.

**Commit:** `feat(api): remnawave client interface + in-memory mock`
**Effort:** 40 мин.

---

### T3 — `/internal/trials` реальная реализация

**Что:**
- Request: `TrialCreateIn { tg_id, phone_e164, ip_hash, referral_source: str | None }`.
- Flow в единой транзакции (`async with session.begin():`):
  1. SELECT user by tg_id. Create if missing (status=ACTIVE,
     `referral_source` из запроса если указано).
  2. Compute `fingerprint = sha256(phone_e164 + str(tg_id) + settings.fp_salt)`.
  3. SELECT FROM trials WHERE tg_id = :tg_id OR fingerprint_hash = :fp
     FOR UPDATE. Если найдено → 409 `trial_already_used`.
  4. Call `remnawave.create_user(new_sub_id, plan='trial', ttl_days=3)`.
  5. INSERT subscription (status=TRIAL, expires_at=now+3d, plan='trial',
     remna_user_id, sub_token).
  6. INSERT trial (tg_id, fingerprint_hash, subscription_id, ip_hash).
  7. INSERT audit_log (action='trial_issued', payload={referral_source}).
- Response: `SubscriptionOut { sub_token, expires_at, status, plan }`.
- Тесты: happy path, повторный запрос тем же tg_id → 409, повторный с
  другим tg_id но тем же phone → 409, невалидный phone → 422.

**Commit:** `feat(api): trial issuance endpoint with fingerprint dedup`
**Effort:** 90 мин.

---

### T4 — `/internal/codes/activate` реальная реализация

**Что:**
- Request: `CodeActivateIn { tg_id, code, ip_hash, referral_source: str | None }`.
- Flow:
  1. **Rate-limit check**: Redis `rl:code:{tg_id}` — INCR, если >5 за 10 мин
     → INSERT code_attempt (result='rl'), 429 `rate_limited`.
  2. SELECT user FOR UPDATE (create if missing, `referral_source` если указано
     и user новый).
  3. Резолв кода: `WHERE code_hash = sha256(code_input)` (unique index из
     Stage 0 T1). На совпадение — расшифровать `code_enc` и сверить equality
     для защиты от theoretical hash collision.
  4. Если не найден → INSERT code_attempt(result='bad'), 404 `code_not_found`.
  5. Если `status != ACTIVE` или `expires_at < now` или `used_at != null`
     (single-use) → соответствующий error, code_attempt(result='expired/used').
  6. Если `reserved_for_tg_id != null` и `!= tg_id` → 403 `code_reserved`.
  7. SELECT current subscription WHERE user_id=:uid AND status='ACTIVE'
     FOR UPDATE.
  8. **Продление vs замена:**
     - Если нет активной → создать новую (как в trial, но plan из кода).
     - Если активная **того же плана** → extend (remnawave.extend + UPDATE
       expires_at += code.duration_days).
     - Если активная **другого плана** → revoke старую (remnawave.revoke),
       создать новую. audit log action='subscription_replaced'.
  9. UPDATE code SET used_at=now, used_by_user_id=:uid, status='USED'
     (если single-use). Для multi-use — декремент `uses_remaining`.
  10. INSERT audit_log (action='code_activated', payload={plan, duration}).
  11. INSERT code_attempt(result='ok').
- Response: `SubscriptionOut`.
- Тесты: 12 сценариев (happy, wrong code, expired, used, reserved for other,
  reserved for self, RL exceeded, extend same plan, replace other plan,
  no-sub → new, multi-use decrement, concurrent activation → 1 wins).

**Commit:** `feat(api): code activation with extend/replace logic + rate-limit`
**Effort:** 180 мин.

---

### T5 — `/internal/users/{tg_id}/subscription` GET

**Что:**
- SELECT user LEFT JOIN subscription WHERE user.tg_id = :tg AND
  subscription.status IN ('ACTIVE','TRIAL').
- Если нет → `{ "status": "NONE" }`.
- Иначе → `SubscriptionOut { status, plan, expires_at, sub_token }`.
- `sub_token` используется фронтом Mini-App для запроса sub URL (Stage 2).
- Тесты: NONE / ACTIVE / TRIAL / EXPIRED (фильтруется).

**Commit:** `feat(api): get user subscription endpoint`
**Effort:** 30 мин.

---

### T6 — `/internal/mtproto/issue` реальная реализация

**Что:**
- Request: `MtprotoIssueIn { tg_id, scope: 'shared'|'user' }`.
- Flow:
  1. Validate user has active subscription (иначе 403).
  2. Если `scope=shared` → SELECT random MtprotoSecret WHERE status='ACTIVE'
     AND scope='shared'. Если нет — 503.
  3. Если `scope=user` → создать новый секрет (генерация 32 hex),
     INSERT MtprotoSecret(scope='user', user_id=:uid, cloak_domain=next_cloak).
     Cloak domain pool — из `settings.mtg_cloak_domains` (list).
     (Реальная отправка config в mtg-nodes — Stage 5.)
  4. INSERT audit_log (action='mtproto_issued', scope, secret_id).
- Response: `{ tg_proxy_url: "tg://proxy?server=...&port=443&secret=ee...<domain-hex>" }`.
- Тесты: shared happy, user happy, no-subscription → 403, no shared pool → 503.

**Commit:** `feat(api): mtproto secret issuance endpoint`
**Effort:** 60 мин.

---

### T7 — Bot: refactor handlers to use real API

**Что:**
- `bot/app/handlers/common.py`:
  - `/start` парсит `message.text.split(maxsplit=1)[1]` как payload.
    Если есть — `redis.set(f"dl:{tg_id}", payload, ex=7*86400)`.
    (НЕ создаёт user в БД — это произойдёт в первом mutating вызове.)
  - Главное меню: добавить кнопку «💳 Показать подписку».
- `bot/app/handlers/activation.py`:
  - FSM state `AWAITING_CODE`.
  - Текст-ответ: валидировать `re.fullmatch(r"[A-Z0-9]{8,16}", text)`.
  - Перед вызовом: `referral_source = await redis.get(f"dl:{tg_id}")`.
  - Вызов `api_client.activate_code(tg_id, code, ip_hash, referral_source)`.
  - При 200 — `redis.delete(f"dl:{tg_id}")`.
  - Обработка ответов: 200 → «✅ Код активирован. Подписка активна до ...».
    404 → «Код не найден». 429 → «Слишком много попыток…». 403 → «Код не
    предназначен для вас». 409 → «Код уже использован».
- `bot/app/handlers/trial.py` (новый):
  - «🎁 Получить триал» → проверка `users.phone_e164` в БД. Если нет —
    отправить ReplyKeyboardMarkup с `KeyboardButton(request_contact=True)`.
  - Contact handler — проверить `message.contact.user_id == message.from_user.id`,
    сохранить phone_e164.
  - Перед вызовом: `referral_source = await redis.get(f"dl:{tg_id}")`.
  - Вызов `trials/create` с `referral_source`.
  - При 200 — `redis.delete(f"dl:{tg_id}")`.
  - Обработка ответов.
- `bot/app/handlers/subscription.py`:
  - `GET /internal/users/{tg_id}/subscription`.
  - Если ACTIVE/TRIAL — отправить кнопку с `web_app=WebAppInfo(url=f"{WEBAPP_URL}?token={sub_token}")`.
  - Если NONE — предложить триал/код.
- `bot/app/handlers/mtproto.py`:
  - Кнопки «Общий» / «Личный» → вызов `mtproto/issue`.
  - Ответ — tg://proxy ссылка + инструкция.
- Текст-тесты через `aiogram.types.Update.model_validate` + mock API.

**Commit:** `feat(bot): wire handlers to real internal API`
**Effort:** 180 мин.

---

### T8 — Reminders worker (arq)

**Что:**
- `api/app/workers/reminders.py`:
  - `arq` worker, cron `*/15 * * * *`.
  - SELECT subscriptions WHERE status='ACTIVE' AND expires_at BETWEEN now
    AND now+24h.
  - Для каждой: определить bucket (`24h|6h|1h`) — наименьший ещё не
    отправленный. Проверить `reminder_log` (новая таблица в Stage 0 или
    здесь — **решение:** добавим в Stage 0 T1, update миграции).
  - Отправить через `bot.send_message` (импорт из bot-сервиса? или вызов
    через HTTP-endpoint бота). **Decision:** reminders worker живёт в
    api-контейнере, держит aiogram-клиент в read-only режиме (просто
    `Bot(token).send_message`). Без polling.
  - INSERT reminder_log (subscription_id, bucket, sent_at).
- `docker-compose.dev.yml`: новый сервис `reminders` с тем же образом
  api, но CMD `python -m app.workers.reminders`.
- Тесты: mock `datetime.now`, проверить корректный bucket selection.

**Commit:** `feat(api): subscription expiry reminders worker`
**Effort:** 120 мин.

---

### T9 — Integration test suite по ТЗ §4

**Что:**
- `api/tests/test_flows.py`:
  - Scenario 1: trial → mini-app sub-url → expired → activate code → extended.
  - Scenario 2: activate code without trial → subscription active.
  - Scenario 3: fingerprint abuse attempt → 409.
  - Scenario 4: RL on code → 429.
  - Scenario 5: code_reserved mismatch → 403.
  - Scenario 6: concurrent activate (asyncio.gather x2) → один wins.
- Использовать testcontainers для Postgres + fakeredis.
- Coverage report: `pytest --cov=app --cov-report=term-missing --cov-fail-under=80`.

**Commit:** `test(api): integration coverage for TZ §4 flows`
**Effort:** 150 мин.

---

### T10 — CHANGELOG + docs update

**Что:**
- CHANGELOG: `## [0.1.0] - 2026-04-xx` со всеми T1-T9.
- Обновить `docs/ARCHITECTURE.md` (если появятся новые таблицы: `reminder_log`,
  `code_hash` column).
- Обновить `README.md` dev-quickstart (новый reminders-сервис).

**Commit:** `docs: update changelog + architecture for stage-1`
**Effort:** 20 мин.

---

## 3. Порядок исполнения

```
T1 (hmac)        → блокирует всё, делать первым
T2 (remna mock)  → параллельно T1
T3 (trials)      → после T1+T2
T4 (activate)    → после T1+T2, **требует code_hash колонку** (ретрофит Stage 0 миграции)
T5 (get sub)     → после T1
T6 (mtproto)     → после T1, требует MtprotoSecret pool seed-data
T7 (bot)         → после T3-T6
T8 (reminders)   → после T3+T4 (должны создаваться реальные subs)
T9 (tests)       → параллельно T3-T8 (TDD приветствуется)
T10 (docs)       → последним
```

**Критичный prerequisite (закрыт в Stage 0 T1):**
- Колонка `codes.code_hash CHAR(64) NOT NULL UNIQUE` — добавлена в `0001_init.py`.
- Таблица `reminder_log (subscription_id, bucket, sent_at, PK (sub_id, bucket))` —
  добавлена в `0001_init.py`.

Если Stage 0 ещё не смержен на момент старта Stage 1 — блокируемся, не делаем
ретрофит-миграции.

---

## 4. Риски и митигации

| Риск | Митигация |
|---|---|
| Full-scan codes при резолве (N→∞) | `code_hash` индекс добавлен заранее |
| Race на активацию одного кода | `SELECT ... FOR UPDATE` на code и subscription |
| Remnawave mock рассинхронизирован с реальным API | ABC интерфейс + контрактные тесты (Stage 2 должен пройти те же тесты с реальным клиентом) |
| `arq` падает, reminders не отправляются | Alert на missed cron в Stage 6; пока — логирование и retry |
| `Contact` handler ловит contact не того юзера (share чужого контакта) | Проверять `message.contact.user_id == message.from_user.id` |
| tg://proxy ссылка с user-secret утекает в логи | Логировать только `secret_id`, не секрет |
| Fake-redis расхождения со sliding window | Использовать реальный Redis в compose-test профиле |

---

## 5. Out of scope

Явно откладываем на Stage 2+:
- Реальный Remnawave HTTP-клиент.
- Деплой Cloudflare sub-Worker и генерация подписочных URL с конвертацией
  клиентов (Clash/Sing-box/v2rayN).
- Admin panel API (`/admin/*` endpoints, RBAC, JWT).
- Node health probing + IP rotation.
- Observability (Loki/Grafana).
- Captcha после RL (пока просто «подожди 10 мин»).
- Prometheus metrics endpoints.

---

## 6. Post-Stage-1

После мерджа:
1. CHANGELOG → `[0.1.0]`.
2. Открыть `docs/plan-stage-2.md` — Cloudflare Workers (sub + DoH) + Remnawave
   real client + Admin API skeleton.
3. Demo юзеру: триал → код → MTProto → Mini-App загружается (UI ещё
   placeholder из Stage 0).

---

## 7. Non-negotiables check-list (self-review перед PR)

- [ ] Нет `# type: ignore` в `api/app/` и `bot/app/`.
- [ ] Нет `as any` / `@ts-ignore` в TS (в этом этапе TS почти не трогаем).
- [ ] Все ошибки — через `HTTPException(status_code, detail={"code": "...", "message": "..."})`.
- [ ] IP в логах — только `sha256(ip + IP_SALT)`.
- [ ] Телефоны в логах — только `phone_hash` или `***last4`.
- [ ] Код и xray_uuid — encrypted в БД (secretbox из Stage 0 T2).
- [ ] Каждый mutating endpoint пишет audit_log.
- [ ] Все `/internal/*` требуют HMAC.
- [ ] Rate-limit активен на `/internal/codes/activate`.
- [ ] `1 active subscription per user_id` — через partial unique index
      (Stage 0 T1) + `FOR UPDATE` в транзакциях.
- [ ] Coverage ≥80% на затронутых модулях.
