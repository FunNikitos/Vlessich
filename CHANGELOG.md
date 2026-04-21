# Changelog

Все значимые изменения этого проекта документируются в этом файле.

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

## [0.1.0] — 2026-04-21 — Stage 1: Backend + Bot MVP

### Added
- **api**: `app/errors.py` — `ApiCode` enum + `api_error()` helper that
  produces the canonical `{code, message}` response envelope; wired via a
  global `HTTPException` handler flattening `detail` to the top level.
- **api**: `POST /internal/trials` — реальная реализация с
  fingerprint dedup (`sha256(phone|tg_id|fp_salt)`), `SELECT FOR UPDATE`
  на user, интеграция с `RemnawaveClient`, вставкой subscription (TRIAL),
  trial row и audit_log — всё в одной транзакции.
- **api**: `POST /internal/codes/activate` — транзакционная активация с
  Redis-rate-limit (5/10мин/tg_id), lookup по `code_hash` (unique index),
  defense-in-depth сверкой plaintext, extend/replace/create стратегиями,
  revoke предыдущей подписки через Remnawave и записью `code_attempts` для
  каждого результата (`ok|bad|rl|expired|used|reserved`).
- **api**: `GET /internal/users/{tg_id}/subscription` — возвращает
  `SubscriptionOut` для ACTIVE/TRIAL или `{status: NONE}`.
- **api**: `POST /internal/mtproto/issue` — требует активную подписку;
  `scope=shared` отдаёт старейший ACTIVE secret из пула (или 503
  `no_shared_mtproto_pool`), `scope=user` минит новый секрет с load-balance
  по `settings.mtg_cloak_domains`.
- **api**: `app/services/remnawave.py` — `RemnawaveClient` ABC +
  `MockRemnawaveClient` (in-memory) + DI `get_remnawave()`; Stage 2 swap
  на HTTP implementation не требует изменений в бизнес-логике. Тесты:
  `api/tests/test_remnawave.py`.
- **api**: `app/workers/reminders.py` — отдельный send-only aiogram.Bot
  воркер, идемпотентный через `reminder_log (subscription_id, bucket)`,
  bucket'ы 24h/6h/1h. `docker-compose.dev.yml::reminders` запускает его
  с образом api и CMD `python -m app.workers.reminders`.
- **api**: `app/ratelimit.py::check_code_rate_limit` — sliding-window
  INCR/EXPIRE anti-abuse limiter для активации кодов.
- **api**: `app/db.get_redis/init_redis/close_redis` — общий Redis
  клиент в lifespan.
- **api**: HMAC wire format зафиксирован в `app/security._compute_signature`
  + `api/tests/test_security.py` (bad/stale/missing signature rejected,
  format lock vs bot ApiClient).
- **api**: settings `fp_salt`, `ip_salt`, `trial_days`, `code_rl_attempts`,
  `code_rl_window_sec`, `mtg_cloak_domains`, `mtg_host`, `mtg_port`.
- **bot**: `services/deeplink.py` — capture/consume/drop `dl:{tg_id}`
  (TTL 7д, truncate 128 chars). `/start <payload>` handler сохраняет
  payload, первый mutating вызов подставляет в `referral_source`.
- **bot**: `handlers/trial.py` — Contact-button flow с проверкой
  `contact.user_id == from_user.id`, POST triala с `phone_e164`.
- **bot**: `handlers/subscription.py` — рендер NONE/ACTIVE/TRIAL,
  Mini-App кнопка с `?token=sub_token` при установленном `BOT_WEBAPP_URL`.
- **tests**: `api/tests/test_helpers.py` (fingerprint, mtproto deeplink),
  `api/tests/test_flows_integration.py` (TZ §4: trial/RL/fingerprint
  abuse/single-use concurrency — SKIP без `VLESSICH_INTEGRATION_DB`),
  `bot/tests/test_deeplink.py` (5 unit-тестов на fakeredis).

### Changed
- **api**: `app/schemas.py` — унифицирован `SubscriptionOut`
  (`status: NONE|ACTIVE|TRIAL|EXPIRED|REVOKED`, `sub_token`, `plan`,
  `expires_at`, `devices_limit`). `ActivateCodeIn`/`TrialIn` принимают
  `ip_hash` и `referral_source`. `MtprotoIn` получил `scope`.
- **bot**: `ApiClient` переписан под единый `Subscription` dataclass;
  `create_trial` теперь требует `phone_e164`; новые аргументы `ip_hash`,
  `referral_source`, `scope` прокидываются в запросы.
- **bot**: `handlers/common.py` — добавлена кнопка «💳 Показать подписку»,
  `CommandStart(deep_link=True)` capture.
- **bot**: `handlers/activation.py` — formatting relaxed до `[A-Z0-9-]{4,32}`;
  пулит `referral_source` из cache, дропает ключ после успеха.
- **bot**: `main.py::build_dispatcher` — `dp["redis"] = redis` для DI.
- **texts**: `SUBSCRIPTION_BLOCK` разделён на `SUBSCRIPTION_NONE`/`ACTIVE`;
  добавлены `TRIAL_PHONE_REQUEST`, `TRIAL_PHONE_BAD_OWNER`.

### Removed
- Устаревший bot `handlers/activation.py::trial_start` (заменён на
  `trial.py` с Contact flow).

### Notes
- Stage 1 non-negotiables пройдены: нет `as any` / `@ts-ignore` /
  `@ts-expect-error` / `# type: ignore` в исполняемом коде; все ошибки
  идут через `api_error()` с `{code, message}`; все mutating endpoints
  пишут audit_log; IP хэшируется в `ip_hash` (CHAR(64)); коды и
  xray_uuid хранятся зашифрованными (`code_enc`, `xray_uuid_enc`).
- `pytest`, `mypy --strict`, `alembic upgrade head`, `npm install` не
  запускались локально (Windows-dev без MSVC/node). Запуск полного
  toolchain ожидается на dev-машине перед merge в `master`.

## [0.0.1] — 2026-04-20 — Stage 0: Scaffold complete

### Added
- `docs/ARCHITECTURE.md` — Mermaid component diagram, 5 sequence diagrams
  (trial, code activation, sub URL, IP rotation, MTProto issuance), ERD,
  security boundaries, deploy topology.
- `docs/plan-stage-0.md`, `docs/plan-stage-1.md` — атомарные планы этапов
  с DoD, рисками, порядком исполнения.
- **api**: первая alembic миграция `0001_init.py` (T1), создаёт все таблицы
  для Stage 1 (`users`, `nodes`, `codes`, `subscriptions`, `devices`,
  `trials`, `mtproto_secrets`, `audit_log`, `code_attempts`, `reminder_log`)
  + расширение `pgcrypto`.
- **api**: модели `Trial`, `Node`, `MtprotoSecret`, `AuditLog`,
  `CodeAttempt`, `ReminderLog`. Поля `users.phone_e164`,
  `users.referral_source`. Партиционный unique-индекс на
  `subscriptions(user_id) WHERE status IN ('ACTIVE','TRIAL')` —
  инвариант TZ §4.5.
- **api**: `codes.code_hash CHAR(64) UNIQUE` для O(log N) lookup без
  full-scan расшифровки (Stage 1 prereq).
- **api**: `app/crypto.py` — `SecretBoxCipher` (libsodium) + 5 unit-тестов
  (roundtrip, distinct ciphertexts, wrong-key, tamper, bad key length) (T2).
- **bot**: `handlers/_utils.py::resolve_cb()` — narrowing helper для
  `CallbackQuery.message`, заменяет 4 `# type: ignore[union-attr]` (T3).
- **bot**: Redis-based `ThrottlingMiddleware` (sliding window, INCR+EXPIRE),
  fail-open на Redis ошибках, разные prefix для message/callback (T4).
- **bot**: `fakeredis>=2.26` в dev-deps + 6 unit-тестов throttling.
- **dev**: `mailhog` сервис в `docker-compose.dev.yml` (SMTP catcher,
  127.0.0.1:1025 + UI 8025) (T5).
- **make**: `frontend-install` target; пре-flight `Подготовка` секция в
  `ansible/README.md` с чек-листом перед `make deploy-node` (T6, T7).
- **ansible**: `group_vars/all.yml.example`, `group_vars/vpn_nodes/vault.yml.example`
  с предупреждением о том, что пустой `ssh_pubkeys` после fwknop = недоступная нода (T7).
- **pre-commit**: 6 frontend hook'ов (prettier/eslint/tsc × webapp/admin)
  на `local`/`system` lang (T8).
- **frontend**: `prettier` + `prettier-plugin-tailwindcss` в обоих
  `package.json` + общий `.prettierrc.json`.

### Changed
- **bot**: `bot/app/main.py` — single Redis client разделяется между FSM
  storage и throttling middleware, корректный `aclose()` на shutdown.
- **api/bot config**: `Settings.model_validate({})` вместо `Settings()  # type: ignore[call-arg]` —
  zero `# type: ignore` в исполняемом коде.
- **bot**: `services/api_client.py` — explicit `isinstance(parsed, dict)`
  narrowing вместо `# type: ignore[no-any-return]`; malformed response →
  `ApiError`.
- **make**: все frontend цели переведены с `pnpm` на `npm --prefix`
  (нет `pnpm-lock.yaml` в репо).
- **api**: `Code.code` (Text, plaintext) → `Code.code_enc` (LargeBinary,
  encrypted) + новая колонка `Code.code_hash` (CHAR(64) UNIQUE).
- **api**: `Subscription` получил поля `plan`, `remna_user_id`,
  `current_node_id`.
- **gitignore**: `ansible/inventory/hosts.yml`, `ansible/group_vars/all.yml`,
  `ansible/group_vars/vpn_nodes/vault.yml` исключены; `*.example`
  отслеживаются.

### Removed
- `bot/app/middlewares/throttling.py` старая in-memory реализация
  (заменена Redis-based).
- 4× `# type: ignore[union-attr]` в bot handlers, 1× `# type: ignore[no-any-return]`
  в api_client, 2× `# type: ignore[call-arg]` в config — всего 7 escape hatches.

### Notes
- `make up` на чистом клоне теперь поднимает db + redis + api + bot +
  webapp + admin + mailhog без падений (alembic миграция применяется).
- Stage 1 разблокирован: `code_hash` index + `reminder_log` готовы.
