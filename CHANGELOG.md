# Changelog

Все значимые изменения этого проекта документируются в этом файле.

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

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
