# Stage 0 — Scaffold completion

**Версия:** 1.0
**Дата:** 20.04.2026
**Статус:** ⏳ pending approval → execute
**Срок:** ~3-4 часа работы одним инженером/агентом.

---

## 0. Контекст

ТЗ (`TZ.md` §16, Этап 0) декларирует «монорепо-структура, docker-compose.dev,
pre-commit, CI, Makefile, ARCHITECTURE.md». Большая часть уже создана ранее
(bot/api/webapp/admin/ansible/infra/caddy/mtg + CI). Но при глубокой
верификации обнаружены **9 блокеров**, мешающих:

1. Запустить `make up` на чистой машине (alembic упадёт, нет mailhog).
2. Запустить тесты через `make test` (pnpm vs npm).
3. Принять production-трафик от первой FI-ноды (нет inventory/hosts.example).
4. Соблюсти non-negotiable rules (type-ignore в боте, in-memory RL).
5. Начать Этап 1 (нет моделей Trial/AuditLog/Node, нет crypto).

Этот этап **не добавляет бизнес-логики** — только завершает scaffold.
После мерджа — переход к Этапу 1.

---

## 1. Definition of Done

Этап 0 закрыт, когда выполнены **все** пункты:

- [ ] `make up` на чистом клоне поднимает db + redis + api + bot + webapp +
      admin + mailhog без ошибок; `/healthz` отвечает `200 ok`.
- [ ] `make test` запускает pytest (bot+api) и vitest (webapp+admin) без
      ошибок (скелетные smoke-тесты).
- [ ] `make lint` и `make typecheck` зелёные на всех 4 модулях.
- [ ] `pre-commit run --all-files` проходит.
- [ ] `terraform -chdir=infra fmt -check && terraform -chdir=infra validate`
      зелёные.
- [ ] `ansible-lint ansible/` без ошибок.
- [ ] В `bot/app/` отсутствуют `# type: ignore`, `as any`, пустые `except:`.
- [ ] В `api/alembic/versions/` есть первая миграция `0001_init.py`, и
      `alembic upgrade head` применяет её на пустой БД.
- [ ] `docs/ARCHITECTURE.md` существует и рендерится (Mermaid).
- [ ] `docs/plan-stage-0.md` (этот файл) отмечен как «done» в CHANGELOG.

**Success metric:** junior-инженер клонирует репо, следует `README.md`,
получает работающую dev-среду за <10 минут без правок.

---

## 2. Задачи (атомарные)

Каждый пункт = один коммит (Conventional Commits), одна проверка.

### T1 — Alembic initial migration [B1]

**Почему:** `docker-compose.dev.yml` запускает `alembic upgrade head` до
старта uvicorn. На чистой БД миграций нет → контейнер api упадёт в loop.
Дополнительно: Stage 1 требует `code_hash` индекс и `reminder_log`
таблицу — закладываем сразу, чтобы не плодить `0002_stage1_prep.py`.

**Что:**
- Расширить `api/app/models.py`, добавив (согласно TZ §12 и ARCHITECTURE §10):
  - `Trial` (tg_id, fingerprint_hash, issued_at, subscription_id, ip_hash)
  - `Node` (hostname, current_ip, status: `HEALTHY|BURNED|MAINTENANCE`,
    last_probe_at, provider, region)
  - `MtprotoSecret` (secret_hex unique, cloak_domain, scope `shared|user`,
    user_id nullable, status, created_at, rotated_at)
  - `AuditLog` (id, actor_type `system|admin|user|bot`, actor_ref, action,
    target_type, target_id, payload jsonb, at)
  - `CodeAttempt` (id, tg_id, code_attempted, result `ok|bad|rl|expired`,
    ip_hash, at)
  - `ReminderLog` (subscription_id FK, bucket `24h|6h|1h`, sent_at,
    PK `(subscription_id, bucket)`) — идемпотентность рассылки (Stage 1).
- Дополнить существующую модель `Code`:
  - Добавить колонку `code_hash CHAR(64) NOT NULL UNIQUE` —
    `sha256(plaintext_code)` для O(log N) резолва без full-scan расшифровки
    (требование Stage 1 T4).
  - Колонка `code` остаётся encrypted (secretbox), но lookup идёт по hash.
  - Equality-сверка после расшифровки — защита от theoretical hash collision.
- Добавить FK: `subscriptions.current_node_id → nodes.id`.
- Добавить constraint: `unique partial index on subscriptions(user_id) where status='ACTIVE'`
  (инвариант TZ §4.5).
- Запустить `alembic revision --autogenerate -m "init"` в dev-контейнере.
- Проверить сгенерированную миграцию руками (autogenerate иногда путает типы).
- Закоммитить `api/alembic/versions/0001_init.py`.

**Проверка:**
```
docker compose -f docker-compose.dev.yml up -d db
cd api && alembic upgrade head && alembic downgrade base && alembic upgrade head
```
Всё проходит без ошибок, таблицы создаются, `alembic current` показывает head.

**Commit:** `feat(api): initial schema migration + extended models`
**Effort:** 60 мин (+15 за счёт code_hash и reminder_log).

---

### T2 — Crypto module (libsodium secretbox) [B2]

**Почему:** `Device.xray_uuid_enc: bytes` и `codes.reserved_for_tg_id`
требуют at-rest encryption (non-negotiable rule #3). Нет модуля — нельзя
реализовать Этап 1.

**Что:**
- Создать `api/app/crypto.py`:
  ```python
  class SecretBoxCipher:
      def __init__(self, key_hex: str): ...
      def seal(self, plaintext: str) -> bytes: ...
      def open(self, ciphertext: bytes) -> str: ...
  ```
- Ключ из `settings.secretbox_key` (64 hex chars = 32 bytes).
- Nonce per-message (24 bytes, prepended to ciphertext).
- Использовать `nacl.secret.SecretBox` из `pynacl` (уже в deps).
- Lru-cached singleton accessor `get_cipher()`.
- Unit-тесты: roundtrip, tamper detection, wrong-key detection.

**Проверка:**
```
cd api && pytest tests/test_crypto.py -v
```
3 теста, все pass.

**Commit:** `feat(api): add libsodium secretbox cipher for at-rest encryption`
**Effort:** 30 мин.

---

### T3 — Remove type-ignore from bot handlers [B4]

**Почему:** Non-negotiable rule #1. 4 ignore в `activation.py`,
`subscription.py`, `mtproto.py` на `cb.message.answer()`.

**Что:**
Заменить `cb.message.answer(...)  # type: ignore[union-attr]` на:
```python
from aiogram.types import Message

async def ...(cb: CallbackQuery, ...) -> None:
    if cb.from_user is None or not isinstance(cb.message, Message):
        await cb.answer()
        return
    await cb.message.answer(...)
    await cb.answer()
```

Повторяющийся guard — вынести в util `bot/app/handlers/_utils.py`:
```python
def ensure_message(cb: CallbackQuery) -> tuple[User, Message] | None: ...
```

**Проверка:**
```
cd bot && mypy --strict app && grep -rn "type: ignore" app/  # empty
```

**Commit:** `refactor(bot): remove type-ignore via proper narrowing`
**Effort:** 20 мин.

---

### T4 — Redis-based throttling middleware [B5]

**Почему:** `bot/app/middlewares/throttling.py` — in-memory dict (не
переживает restart, не шарится между replicas). ТЗ §5.5 требует Redis RL.

**Что:**
- Переписать `ThrottlingMiddleware`:
  ```python
  class ThrottlingMiddleware(BaseMiddleware):
      def __init__(self, redis: Redis, rate: int, per_seconds: int): ...
  ```
- Использовать sliding-window через `INCR` + `EXPIRE` на ключе
  `rl:msg:{tg_id}:{bucket_10s}`.
- Wire в `main.py`: создать `redis.asyncio.from_url(settings.redis_url)`
  и передать в middleware.
- Настройки — per-feature rate (общий throttle 1/0.5s, отдельно — для
  future code-attempt middleware).
- Тест: mock redis через `fakeredis`, проверить отказ на 2-м вызове в
  окне 500ms.

**Проверка:** unit-тест + логический smoke через `pytest`.

**Commit:** `feat(bot): redis-based throttling middleware`
**Effort:** 40 мин.

---

### T5 — Mailhog service in docker-compose.dev [B6]

**Почему:** ТЗ Этап 0 требует Mailhog. Сейчас его нет. Нужен для будущих
email-уведомлений (Этап 6, alert bus).

**Что:**
Добавить в `docker-compose.dev.yml`:
```yaml
  mailhog:
    image: mailhog/mailhog:v1.0.1
    restart: unless-stopped
    ports:
      - "127.0.0.1:1025:1025"   # SMTP
      - "127.0.0.1:8025:8025"   # Web UI
```
Упомянуть в корневом `README.md` («SMTP dev: localhost:1025, UI:
http://localhost:8025»).

**Проверка:** `docker compose up mailhog` + `curl -I http://localhost:8025` → 200.

**Commit:** `chore(dev): add mailhog to docker-compose.dev`
**Effort:** 5 мин.

---

### T6 — Fix Makefile pnpm/npm inconsistency [B7]

**Почему:** `make test` делает `pnpm test`, но frontend `package.json`
не настроен под pnpm (нет `pnpm-lock.yaml`). На чистой машине падает.

**Что:**
- В `Makefile` заменить `pnpm` → `npm` в целях `test`, `lint`, `typecheck`
  (секции webapp/admin).
- Добавить `.PHONY: frontend-install` с `npm install --prefix webapp
  && npm install --prefix admin`.
- Упомянуть в README.

**Проверка:**
```
make frontend-install && make typecheck
```

**Commit:** `fix(make): align frontend commands to npm`
**Effort:** 10 мин.

---

### T7 — Ansible inventory example + SSH pubkey reminder [B8]

**Почему:** `ansible/README.md` ссылается на `inventory/hosts.example.yml`,
файла нет. Без ssh_pubkeys после fwknop нода становится недоступной.

**Что:**
- Создать `ansible/inventory/hosts.example.yml`:
  ```yaml
  all:
    children:
      vpn_nodes:
        hosts:
          fi-01:
            ansible_host: 203.0.113.10      # REPLACE
            ansible_user: root              # initial bootstrap
            ansible_port: 22                # пока fwknop не включён
            node_name: fi-01.example.com
  ```
- Создать `ansible/group_vars/all.yml.example` с `ssh_pubkeys: []` и
  комментарием «MUST be filled before first run, иначе после fwknop SSH
  не пустит».
- Создать `ansible/group_vars/vpn_nodes/vault.yml.example` со списком
  требуемых vault_* переменных (без значений).
- В README ansible/README.md — чёткая инструкция «что заполнить перед
  первым `make deploy-node`».

**Проверка:** `ansible-inventory -i inventory/hosts.example.yml --list`
без ошибок.

**Commit:** `docs(ansible): add inventory + group_vars examples`
**Effort:** 15 мин.

---

### T8 — Prettier/eslint pre-commit hooks for frontend [soft-B]

**Почему:** ТЗ Этап 0 «pre-commit: ruff, mypy, prettier, eslint, tsc».
Сейчас в `.pre-commit-config.yaml` только ruff (python) + terraform +
gitleaks + hadolint. Фронт не проверяется.

**Что:**
Добавить хук:
```yaml
  - repo: local
    hooks:
      - id: frontend-typecheck
        name: tsc --noEmit (webapp+admin)
        entry: bash -c 'npm --prefix webapp run typecheck && npm --prefix admin run typecheck'
        language: system
        pass_filenames: false
        files: '^(webapp|admin)/.*\.(ts|tsx)$'
      - id: prettier
        name: prettier check
        entry: bash -c 'npx --prefix webapp prettier --check webapp admin'
        language: system
        pass_filenames: false
        files: '^(webapp|admin)/'
```
Альтернатива (чище): поставить `prettier` как dev-dep в оба package.json
и вызывать `npm --prefix $MOD run format:check`.

**Проверка:** `pre-commit run --all-files`.

**Commit:** `chore(pre-commit): add frontend typecheck + prettier hooks`
**Effort:** 20 мин.

---

### T9 — docs/ARCHITECTURE.md ✅ (уже создан в этой итерации)

Mermaid component + 5 sequence diagrams + ERD. См. `docs/ARCHITECTURE.md`.
Требуется только code-review от юзера.

**Commit:** `docs: architecture diagrams (component + sequences + ERD)`
(уже частично сделан в этом PR вместе со stage-0 plan).

---

### T10 — CHANGELOG.md init

**Почему:** ТЗ Quality Gates требует обновление CHANGELOG на каждый PR.
Файла нет.

**Что:**
- Создать `CHANGELOG.md` по схеме [Keep a Changelog](https://keepachangelog.com/).
- Первая запись `## [Unreleased]` с пунктами Этапа 0.

**Commit:** включается в финальный Etap-0 commit.
**Effort:** 5 мин.

---

## 3. Порядок исполнения

Работы частично зависимы. Оптимальный порядок:

```
T9  (docs)              → параллельно с T1-T8
T1  (migration)         → блокирует T2, Stage 1
T2  (crypto)            → после T1 (подхватывает models)
T3  (type-ignore)       → независимо
T4  (redis throttling)  → независимо
T5  (mailhog)           → независимо
T6  (Makefile)          → независимо
T7  (ansible examples)  → независимо
T8  (pre-commit)        → последним (зависит от frontend настройки)
T10 (CHANGELOG)         → последним
```

Один инженер/агент может сделать последовательно за ~3 часа.
При параллельной работе (разные PR) — T1 + T2 отдельным треком, остальное
в один PR.

---

## 4. Риски и митигации

| Риск | Митигация |
|---|---|
| `alembic autogenerate` путает `ARRAY(Text)` с `postgresql.ARRAY` | Использовать `sqlalchemy.dialects.postgresql.ARRAY` явно |
| `nacl.secret.SecretBox` падает на wrong key length | Assert на старте: `len(bytes.fromhex(key)) == 32` |
| `fakeredis` не поддерживает `EXPIRE` accurately | Fallback на `freezegun` + реальный Redis в compose-test |
| Prettier «съест» Tailwind class ordering | Подключить `prettier-plugin-tailwindcss` (один раз) |
| `ansible-lint` ругается на custom `node` role | Добавить `.ansible-lint` с `skip_list: [meta-no-info]` если нужно |

---

## 5. Post-Stage-0

После мерджа этого этапа:
1. Обновить `CHANGELOG.md` → раздел `[0.0.1] - 2026-04-20`.
2. Открыть `docs/plan-stage-1.md` (см. отдельный файл).
3. **Ждать аппрува Stage 1 плана** перед написанием бизнес-логики API.

---

## 6. Не в scope Этапа 0

Явно **не трогаем** сейчас, хотя есть соблазн:

- Реализацию activate/trial эндпоинтов — это Stage 1.
- Дизайн Mini-App страниц — это Stage 4.
- Remnawave-клиент — Stage 1/2.
- Cloudflare `provider version ~> 4.40` → 5.x миграцию — Stage 2.5.
- Loki/Grafana control-plane — Stage 6.

Попытка захватить больше = нарушение правила «Surgical Changes» (CLAUDE.md §3).
