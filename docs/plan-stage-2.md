# Stage 2 — Edge (Cloudflare Workers) + Real Remnawave + Admin API

**Версия:** 1.0
**Дата:** 21.04.2026
**Статус:** ⏳ pending approval
**Предпосылка:** Stage 1 завершён (ветка `feat/stage-1-mvp`, HEAD `dd73447`).
**Ветка:** `feat/stage-2-edge` (создана от `feat/stage-1-mvp`).
**Срок:** ~14–18 часов работы.

## Утверждённые решения (locked)

- **Wire-format HMAC для sub-Worker ↔ backend** = **унифицировать с bot↔api форматом**:
  `${METHOD}\n${path}\n${ts}\n${sha256(body)}`. Для GET body=`""` → `sha256("")`.
  Патчим `infra/workers/subscription.js` под этот формат, чтобы
  `api/app/security.py` имел **одну** `verify_signature` без развилок.
  Alternative (две verify-функции) отвергнут: лишняя поверхность атаки.
- **Real Remnawave client** = `httpx.AsyncClient` за тем же ABC
  `RemnawaveClient` (Stage 1 T2). DI-switch по `settings.remnawave_mode`:
  `mock` (dev/test) | `http` (stage/prod). Контрактные тесты гоняем против
  **обоих** реализаций одинаковым набором сценариев.
- **Admin auth** = JWT (HS256, `settings.admin_jwt_secret`) + bcrypt
  password hash. Access-token TTL 1h, refresh 7d в httpOnly cookie. RBAC
  ролей: `superadmin` | `support` | `readonly`. Пользователи админки —
  отдельная таблица `admin_users` (миграция `0002_admin.py`).
- **Pages `build_command`** переезжает с `pnpm` на `npm` (согласовано со
  Stage 0 T6).
- **Sub-Worker payload composer** живёт в backend
  (`api/app/services/sub_payload.py`) и возвращает нормализованный JSON
  `{ inbounds: InboundNode[], meta: {...} }` — Worker конвертирует в
  целевой формат (Clash/sing-box/Surge/v2ray/raw). Это разделяет
  бизнес-логику (backend) и wire-форматы (Worker).

---

## 0. Контекст

ТЗ §7 (sub-Worker), §8 (DoH), §9 (Remnawave integration), §10 (admin panel
backend), §11A.3 (HMAC). Цель — закрыть edge-инфраструктуру и подготовить
контур для Stage 3 (Mini-App визуал) и Stage 4 (Admin UI).

**Что НЕ делаем в этом этапе:**
- Admin UI (React) — Stage 4.
- Mini-App визуал поверх sub-Worker — Stage 3.
- Node health-probe / IP rotation — Stage 5.
- Observability (Loki/Grafana/Prometheus) — Stage 6.
- Captcha — Stage 6.

---

## 1. Definition of Done

- [ ] `GET /internal/sub/{token}` возвращает реальный payload для активной
      подписки (`inbounds[]` + `meta`), с HMAC-проверкой запроса от Worker'а.
- [ ] `infra/workers/subscription.js` подписывает запросы к backend в
      едином формате (`METHOD\npath\nts\nsha256(body)`), проходит
      verify в backend без fork'ов.
- [ ] `infra/workers/doh.js` — без изменений кода (уже production-grade),
      но добавлен `wrangler.toml` для local dev + CI.
- [ ] `HTTPRemnawaveClient` (httpx, async) проходит тот же контрактный
      набор тестов, что и `MockRemnawaveClient`.
- [ ] DI switch `get_remnawave()` по `settings.remnawave_mode`.
- [ ] `admin_users` миграция + bcrypt password storage + `/admin/auth/login`
      выдаёт JWT.
- [ ] `require_admin_role(role: str)` dependency покрывает все `/admin/*`.
- [ ] Admin endpoints (skeleton, реальная логика без UI):
  - `GET /admin/codes` (list + filter + pagination), `POST /admin/codes`
    (generate batch), `DELETE /admin/codes/{id}` (revoke, статус → REVOKED).
  - `GET /admin/users` (list + filter by tg_id/phone_hash).
  - `GET /admin/subscriptions` (list + filter by status).
  - `GET /admin/audit` (last N events).
  - `GET /admin/nodes`, `POST /admin/nodes`, `PATCH /admin/nodes/{id}`.
- [ ] `infra/cloudflare.tf` Pages build_command: `npm ci && npm run build`.
- [ ] Integration tests: sub-Worker → backend (httpx mock на уровне
      backend), admin auth flow, admin codes CRUD.
- [ ] Нет `# type: ignore`, `as any`, пустых `except:` / `catch`.
- [ ] CHANGELOG → `[0.2.0]`.

---

## 2. Задачи (атомарные)

### T1 — `/internal/sub/{token}` real implementation + HMAC unification

**Что:**
- `api/app/security.py`: убедиться что `verify_signature` не требует
  non-empty body для GET (считать `sha256(b"")`).
- `api/app/routers/internal.py`: заменить stub `GET /internal/sub/{token}`:
  1. Lookup `subscriptions.sub_url_token = :token AND status IN ('ACTIVE','TRIAL')`.
  2. Если нет — 404 `{"code":"subscription_not_found"}`.
  3. Вызвать `sub_payload.build_payload(subscription_id)` (см. T2).
  4. Вернуть JSON `{ inbounds, meta: { plan, expires_at, status } }`.
- Unit-тесты: 200 для активной, 404 для несуществующего токена, 404 для
  EXPIRED, HMAC-reject без подписи.

**Commit:** `feat(api): real GET /internal/sub/{token} with payload composer`
**Effort:** 60 мин.

---

### T2 — `sub_payload` composer

**Что:**
- `api/app/services/sub_payload.py`:
  ```python
  @dataclass
  class InboundNode:
      protocol: Literal["vless", "hysteria2", "mtproto"]
      host: str
      port: int
      sni: str | None
      public_key: str | None
      short_id: str | None
      flow: str | None
      path: str | None
      uuid: str | None
      password: str | None
      remarks: str
  
  async def build_payload(session, subscription_id) -> dict: ...
  ```
- Select `nodes` WHERE `status='ACTIVE'`, JOIN `devices` по subscription.
- Для каждой ноды материализовать inbound'ы (VLESS+Reality+Vision,
  VLESS+XHTTP, Hysteria2) с расшифровкой `devices.xray_uuid` через
  secretbox (Stage 0 T2).
- Unit-тесты: mock БД, проверка структуры, проверка что UUID расшифровывается.

**Commit:** `feat(api): subscription inbounds payload composer`
**Effort:** 90 мин.

---

### T3 — `HTTPRemnawaveClient` + контрактные тесты

**Что:**
- `api/app/services/remnawave.py`: добавить `HTTPRemnawaveClient` рядом с
  `MockRemnawaveClient`:
  ```python
  class HTTPRemnawaveClient(RemnawaveClient):
      def __init__(self, base_url: str, api_key: str, timeout: float = 10.0): ...
      async def create_user(...): ...  # POST /api/users
      async def extend_user(...): ...  # PATCH /api/users/{id}
      async def revoke_user(...): ...  # DELETE /api/users/{id}
      async def get_subscription_url(...): ...  # GET /api/users/{id}/subscription
  ```
- Использовать `httpx.AsyncClient`, retry 3x с exp-backoff на 5xx/timeout,
  circuit breaker на 10 последовательных 5xx.
- `api/app/config.py`: `remnawave_mode: Literal["mock","http"] = "mock"`,
  `remnawave_base_url: str | None`, `remnawave_api_key: SecretStr | None`.
- DI `get_remnawave()` читает mode и возвращает нужную реализацию (singleton).
- Контрактные тесты: `api/tests/test_remnawave_contract.py` — параметризованный
  suite, гоняет одинаковые сценарии против mock и http (http мокается через
  `respx`).

**Commit:** `feat(api): http remnawave client with contract tests`
**Effort:** 120 мин.

---

### T4 — Admin auth: JWT + bcrypt + миграция

**Что:**
- Alembic `0002_admin.py`:
  - `admin_users (id UUID PK, email CITEXT UNIQUE, password_hash TEXT,
    role TEXT CHECK IN ('superadmin','support','readonly'), status TEXT,
    created_at TIMESTAMPTZ)`.
- `api/app/auth/admin.py`:
  - `hash_password(plain) -> str` (bcrypt, cost=12).
  - `verify_password(plain, hash) -> bool`.
  - `create_access_token(sub, role, ttl) -> str` (HS256, `settings.admin_jwt_secret`).
  - `decode_token(token) -> AdminClaims`.
- `api/app/routers/admin/auth.py`:
  - `POST /admin/auth/login { email, password }` → `{access_token, role}`.
  - Rate-limit 10/min/email через Redis.
  - Audit log `admin_login` (success/fail).
- Unit-тесты: hash/verify, valid/invalid token, expired token, RL.

**Commit:** `feat(api): admin auth with jwt + bcrypt + rbac schema`
**Effort:** 120 мин.

---

### T5 — Admin RBAC middleware

**Что:**
- `api/app/auth/admin.py::require_admin_role(*roles: str)` — FastAPI
  dependency factory:
  ```python
  def require_admin_role(*allowed: str):
      async def _dep(authorization: Annotated[str, Header()] = ""):
          claims = decode_token(extract_bearer(authorization))
          if claims.role not in allowed:
              raise HTTPException(403, {"code": "forbidden"})
          return claims
      return _dep
  ```
- Роли:
  - `superadmin` — всё.
  - `support` — read + create codes + read users/subs/audit.
  - `readonly` — только GET.
- Unit-тесты для каждой комбинации (role × endpoint).

**Commit:** `feat(api): admin rbac dependency + role matrix`
**Effort:** 60 мин.

---

### T6 — Admin endpoints: codes / users / subscriptions / audit

**Что:**
- `api/app/routers/admin/codes.py`:
  - `GET /admin/codes?status=&plan=&page=&limit=` (readonly+).
  - `POST /admin/codes` body `{ plan, duration_days, count, reserved_for_tg_id?, uses_remaining? }` (support+).
  - `DELETE /admin/codes/{id}` → status='REVOKED' (superadmin).
  - Audit log каждое действие.
- `api/app/routers/admin/users.py`:
  - `GET /admin/users?tg_id=&phone_hash=&page=&limit=` (readonly+).
  - `GET /admin/users/{id}` (readonly+).
- `api/app/routers/admin/subscriptions.py`:
  - `GET /admin/subscriptions?status=&plan=&page=` (readonly+).
  - `POST /admin/subscriptions/{id}/revoke` (superadmin) → remnawave.revoke + status=REVOKED.
- `api/app/routers/admin/audit.py`:
  - `GET /admin/audit?action=&from=&to=&limit=` (readonly+).
- Unit+integration тесты через TestClient + fake JWT.

**Commit:** `feat(api): admin endpoints for codes/users/subs/audit`
**Effort:** 180 мин.

---

### T7 — Admin endpoints: nodes management

**Что:**
- `api/app/routers/admin/nodes.py`:
  - `GET /admin/nodes` (readonly+).
  - `POST /admin/nodes` body `{ hostname, public_ip, country, status }` (superadmin).
  - `PATCH /admin/nodes/{id}` body `{ status?, capacity? }` (superadmin).
  - Валидация: уникальный hostname, country=2-letter ISO.
- Audit log.
- Тесты.

**Commit:** `feat(api): admin nodes management endpoints`
**Effort:** 60 мин.

---

### T8 — Cloudflare Workers: patch HMAC + wrangler.toml + Pages build fix

**Что:**
- `infra/workers/subscription.js`:
  - Патчнуть функцию подписи запроса к backend: вместо `${token}.${ts}`
    считать `SHA-256(METHOD + '\n' + path + '\n' + ts + '\n' + sha256(body))`.
  - Для GET (`path = "/internal/sub/{token}"`, body=`""`) — единая логика.
  - Обновить тесты (inline в README или отдельный `infra/workers/__tests__`).
- `infra/workers/wrangler.subscription.toml` и `wrangler.doh.toml` — для
  локального `wrangler dev` и CI `wrangler deploy --dry-run`.
- `infra/cloudflare.tf`:
  - `build_command = "npm ci && npm run build"` (webapp Pages project)
  - Аналогично для admin Pages project.
- Ручная проверка: `wrangler deploy --dry-run` на оба Worker'а (требует node;
  отложено на CI если нет локально).

**Commit:** `fix(infra): unify worker hmac wire-format + npm pages build`
**Effort:** 60 мин.

---

### T9 — Integration tests: sub-Worker ↔ backend + admin flows

**Что:**
- `api/tests/test_sub_endpoint.py`:
  - Поднять TestClient, сгенерировать валидную sub-Worker подпись
    (emulate Worker), вызвать `/internal/sub/{token}`, проверить payload.
  - Negative: bad sig, clock skew, unknown token.
- `api/tests/test_admin_flow.py`:
  - Login superadmin → create 10 codes → list → revoke 1 → list filtered.
  - Role enforcement: readonly не может POST/DELETE.
- Coverage-gate: ≥80% на `app/routers/admin/`, `app/auth/`, `app/services/sub_payload.py`.

**Commit:** `test(api): integration coverage for sub endpoint + admin flows`
**Effort:** 150 мин.

---

### T10 — CHANGELOG + docs

**Что:**
- CHANGELOG `## [0.2.0] - 2026-04-xx` с T1-T9.
- `docs/ARCHITECTURE.md`: раздел «Admin API» (таблица ролей, матрица прав,
  схема JWT), раздел «Sub-Worker wire contract» (HMAC формат, payload
  schema).
- `README.md`: упомянуть admin endpoints + wrangler dev.

**Commit:** `docs: changelog + admin api + worker contract for stage-2`
**Effort:** 30 мин.

---

## 3. Порядок исполнения

```
T1 (sub endpoint)        → базовый, первым
T2 (payload composer)    → требуется T1 (или параллельно с stub'ом)
T3 (http remna)          → параллельно T1/T2
T4 (admin auth)          → независимо
T5 (rbac)                → после T4
T6 (admin CRUD)          → после T5
T7 (nodes)               → после T5
T8 (workers+tf)          → после T1 (нужен унифицированный HMAC)
T9 (integration tests)   → параллельно T1-T8 (TDD)
T10 (docs)               → последним
```

---

## 4. Риски и митигации

| Риск | Митигация |
|---|---|
| Wrangler deploy на CI без secrets | dry-run only, реальный deploy в Stage 6 |
| HTTPRemnawaveClient протокол расходится с реальным API | контрактный тест + respx mock на основе OpenAPI спеки |
| JWT secret утечка через логи | pydantic `SecretStr`, `.env` в sops, `repr` маскируется |
| bcrypt cost=12 медленный на CI | параметризовать через env, default 12 prod / 4 tests |
| Admin endpoint забыли HMAC/JWT | шаблонный router factory + тест на все `/admin/*` routes |
| sub-Worker кэширует устаревший payload | Cache TTL 60s, revoke через `x-no-cache` header |

---

## 5. Out of scope (→ Stage 3+)

- Mini-App UI (Stage 3).
- Admin UI React (Stage 4).
- Node health-probe, IP rotation (Stage 5).
- Observability, captcha, prometheus (Stage 6).

---

## 6. Non-negotiables check-list

- [ ] Нет `# type: ignore`, `as any`, `@ts-ignore` в добавленном коде.
- [ ] Все ошибки через `HTTPException(status, detail={"code","message"})`.
- [ ] JWT secret/remnawave key — `SecretStr`, в sops.
- [ ] Admin endpoints пишут audit_log.
- [ ] RBAC enforced dependency-wise, нет `if role==...` в handlers.
- [ ] Payload composer не логирует расшифрованные UUID/passwords.
- [ ] HMAC unified, один verify, один sign.
- [ ] Pages build_command = npm (Stage 0 consistency).
- [ ] Coverage ≥80% на затронутых модулях.
