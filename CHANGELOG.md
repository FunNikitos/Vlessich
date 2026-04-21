# Changelog

Все значимые изменения этого проекта документируются в этом файле.

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версионирование — [SemVer](https://semver.org/lang/ru/).

## [Unreleased]

## [0.7.0] — 2026-04-21 — Stage 7: Logs + Alerts + Residential RU Probing

### Added
- **api/workers/probe_backends.py** (новый): `ProbeResult` dataclass,
  `TcpProbeBackend` (перенесён из `prober.py`) и
  `HttpProxyProbeBackend` — GET через residential RU прокси
  (`httpx.AsyncClient(proxy=…)`). Семантика reachability: любой HTTP
  ответ (2xx..5xx) = `ok=True`, transport-error = `ok=False`. RU-блок
  работает на TCP/DNS уровне — статус-код не важен.
- **api/workers/prober.py**: multi-backend режим. `Prober.__init__`
  принимает `backends: list[tuple[str, ProbeBackend]]` (минимум один,
  обязательно `edge`). `run_once` делает `len(nodes) × len(backends)`
  probes в одном `asyncio.gather` и пишет всё в одной транзакции.
  `_build_backends(settings)` собирает `[edge]` всегда + `[ru]` если
  `API_RU_PROXY_URL` задан.
- **api/models.py**: `NodeHealthProbe.probe_source` (varchar(16),
  NOT NULL DEFAULT `'edge'`, CHECK ∈ {`edge`,`ru`}) + индекс
  `ix_node_probes_node_source_probed_at(node_id, probe_source,
  probed_at)`.
- **api/alembic/versions/0004_stage7.py**: миграция column + check +
  index.
- **api/config**: `ru_proxy_url: str | None`,
  `ru_probe_timeout_sec: float = 8.0`.
- **api/workers/prober_metrics.py**: `PROBE_TOTAL` и
  `PROBE_DURATION_SECONDS` теперь labelled `(ok, source)`.
- **infra/prometheus/rules/vlessich.yml** (новый): пять alert rules —
  `NodeBurnSpike`, `ProbeSuccessLow` (only `source="edge"`),
  `ProberDown`, `ApiP95Latency`, `AdminCaptchaFailSpike`. Severity
  convention: `critical` / `warning` / `info`.
- **infra/loki/** (новый): `loki-config.yml` (single-binary, tsdb +
  filesystem, 7d retention), `promtail-config.yml` (Docker SD, JSON
  pipeline, label `service`/`level`/`logger`/`env`),
  `README.md` с deploy-snippet и LogQL примерами.
- **tests**: `test_probe_backends.py` (TCP против ephemeral asyncio
  server + httpx MockTransport для RU), `test_prober_multi_backend.py`
  (Postgres-gated: dual-source rows, RU не зажигает BURN, edge
  зажигает), `test_alert_rules.py` (yaml schema validation).

### Changed
- **api/routers/admin/nodes.py**: `GET /admin/nodes/{id}/health`
  фильтрует `NodeHealthProbe.probe_source == 'edge'` для всех 5
  агрегатов (recent_rows, total_24h, ok_24h, p50, p95) — старая
  семантика сохраняется, RU-данные не загрязняют historic uptime.
- **api/workers/prober.py** state machine реагирует **только** на
  `source == 'edge'`. RU-результаты сохраняются и метрятся, но
  `nodes.status` / `last_probe_at` / `set_node_state` обновляются
  только edge-веткой.
- **api/tests/test_metrics.py** обновлён под новые labelnames
  `(ok, source)`.
- **api/tests/test_prober.py** инициализирует `Prober` с
  `[("edge", backend)]`.

### Security / privacy
- RU residential proxy URL хранится в `API_RU_PROXY_URL` (не
  коммитится). `httpx.AsyncClient(verify=False)` оправдан: проксируем
  публичный hostname через RU exit, важна reachability а не
  TLS-валидность.
- Loki promtail-pipeline не добавляет PII — структурные логи API уже
  маскируют IP через `sha256(ip + IP_SALT)` (см. `app/logging.py`).

### Migration
```bash
alembic upgrade head      # 0004_stage7
# Optional — enable RU probing:
export API_RU_PROXY_URL=socks5://user:pass@proxy.example:1080
docker compose restart prober
```

## [0.6.0] — 2026-04-21 — Stage 6: Observability + Admin Captcha

### Added
- **api/metrics.py**: Prometheus instruments для API — 
  `vlessich_http_request_duration_seconds` (Histogram; labels
  `method`, `path_template`, `status`), `vlessich_admin_login_total`
  (Counter; `result`), `vlessich_subscription_events_total` (Counter;
  `event`).
- **api/main.py**: `MetricsMiddleware` — оборачивает каждый HTTP
  request, observ'ит длительность по route template (bounded
  cardinality), skip `/metrics`. Инкременты:
  - admin login → `success|fail|rate_limited|captcha_fail`,
  - revoke → `subscription_events_total{event=revoked}`,
  - code activate → `issued` (new/replace) + `revoked` (replace).
- **api/workers/prober_metrics.py**: `vlessich_probe_duration_seconds`
  (Histogram; `ok`), `vlessich_probe_total` (Counter), one-hot Gauge
  `vlessich_node_state` через `set_node_state(node, hostname, status)`,
  `vlessich_node_burned_total`, `vlessich_node_recovered_total`.
- **api/workers/prober.py**: `start_http_server(probe_metrics_port)`
  (default 9101) отдельный endpoint `/metrics` для scrape.
- **api/captcha.py**: `TurnstileVerifier` (httpx) + `CaptchaVerifier`
  Protocol + module-level singleton (test-seam). При unset
  `API_TURNSTILE_SECRET` — dev no-op (token ignored).
- **api**: `POST /admin/auth/login` принимает опциональный
  `captcha_token`. Если secret set → обязателен, fail → 400
  `captcha_failed` + метрика. Rate-limit остался.
- **api/config**: `turnstile_secret`, `turnstile_verify_url`,
  `probe_metrics_port`.
- **api/errors**: `ApiCode.CAPTCHA_FAILED`.
- **admin**: `Turnstile` React-компонент (lazy-loaded CDN script, dark
  theme). `LoginPage` показывает widget когда `VITE_TURNSTILE_SITEKEY`
  set, шлёт token в login mutation. `LoginIn` / `useAuth.login` типы
  расширены.
- **infra/grafana/**: `dashboards/vlessich.json` (6 panels — HTTP RPS,
  p95, admin login outcomes, probe success ratio, node states,
  subscription events) + `README.md` с prometheus scrape config для
  `api:8000` и `prober:9101`.
- **infra**: `docker-compose.dev.yml` expose `127.0.0.1:9101` из
  `prober`.
- **tests**: `test_metrics.py` (registry exposure + label values +
  `set_node_state` one-hot), `test_captcha.py`
  (`httpx.MockTransport` — no network).

### Changed
- **admin/src/hooks/useAuth**: сигнатура `login` принимает опциональный
  `captchaToken`.
- **admin/src/lib/types**: `LoginIn.captcha_token`.

### Security
- Turnstile verify на backend — единственный authoritative источник.
  Sitekey на фронте публичен по определению. Secret — **только**
  через `API_TURNSTILE_SECRET` env.
- Rate-limit (10/60s per email) оставлен независимо от captcha —
  defense-in-depth.
- IP для `remoteip` в siteverify берётся из `request.client.host`;
  не логируется в PII-форме, попадает только в Cloudflare edge.



### Added
- **api/workers**: `prober.py` — фоновый воркер, каждые
  `probe_interval_sec` (default 60s) открывает TCP-соединение на
  `hostname:probe_port` (443) с таймаутом `probe_timeout_sec` (5s),
  пишет строку `node_health_probes` для каждой non-MAINTENANCE ноды и
  обновляет `nodes.last_probe_at`. Использует `asyncio.gather` — одна
  зависшая нода не тормозит остальные.
- **api/workers/prober**: BURN/RECOVER state-machine с in-memory
  счётчиком consecutive ok/fail per node:
  - `probe_burn_threshold` (default 3) подряд failures → `nodes.status
    = 'BURNED'` + `AuditLog(action='node_burned')` с payload
    `{hostname, consecutive_fails, last_error}`.
  - `probe_recover_threshold` (default 5) подряд successes → `nodes.
    status = 'HEALTHY'` + `AuditLog(action='node_recovered')`.
  - Counter сбрасывается при transition (hysteresis).
- **api/workers/prober**: `ProbeBackend` Protocol + `TcpProbeBackend`
  (default, asyncio TCP connect). Дизайн позволяет внешнему RU-прокси
  бэкенду вклиниться в Stage 6 без изменения воркера.
- **api**: `POST /admin/nodes/{id}/rotate` (superadmin) —
  подтверждение внешней ротации IP: сбрасывает `current_ip=null`,
  переводит в `HEALTHY`, пишет `AuditLog(action='node_rotated')` с
  `previous_ip` и `previous_status`. 404 для unknown node.
- **api/config**: новые настройки `probe_interval_sec`,
  `probe_timeout_sec`, `probe_port`, `probe_burn_threshold`,
  `probe_recover_threshold` (все env `API_PROBE_*`).
- **admin**: UI-кнопка «Rotate» в `NodesPage` (только superadmin) →
  `ConfirmDestructiveModal` с `confirmWord="ROTATE"` → `api.nodes.
  rotate(id)`. Invalidates `["nodes"]`, `["stats"]`,
  `["node-health", id]`.
- **infra**: `docker-compose.dev.yml` — новый сервис `prober` (reuses
  api image, command `python -m app.workers.prober`).
- **tests**: `test_prober.py` — integration-тесты (scripted backend):
  MAINTENANCE skip, burn threshold, recover threshold, intermittent
  failures не жгут. `test_admin_node_rotate.py` — RBAC (403 support),
  rotate сбрасывает IP+status, audit payload, 404 unknown.

### Changed
- **api/routers/admin/nodes**: добавлен блок rotate перед health
  snapshot handler. Существующие endpoints не изменены.
- **admin/lib/api**: `api.nodes.rotate(id)` метод.

### Security
- Rotate — только для `superadmin` (RBAC enforced на backend, UI
  дополнительно скрывает кнопку).
- Все BURN/RECOVER события логируются с `actor_type='system'`,
  `actor_ref='prober'`.
- Prober TCP-connect не передаёт данных, open→close.

## [0.4.0] — 2026-04-21 — Stage 4: Admin UI + Node Health Dashboard

### Added
- **api**: `GET /admin/stats` — агрегированная сводка для dashboard
  (users/codes/subs/nodes counts + node status buckets:
  HEALTHY/BURNED/MAINTENANCE/STALE). Доступно всем admin-ролям.
- **api**: `POST /admin/subscriptions/{id}/revoke` — отзыв подписки
  (status=`REVOKED`, `expires_at=now()`). Доступно support+. 404 если не
  найдена, 409 если уже в inactive-состоянии.
- **api**: `GET /admin/nodes/{id}/health` — health-карта ноды:
  `uptime_24h_pct`, `latency_p50_ms`, `latency_p95_ms`, последние 50
  probes (`probed_at`, `ok`, `latency_ms`, `error`).
- **api/models**: `NodeHealthProbe` (таблица `node_health_probes`, индекс
  `(node_id, probed_at DESC)`). Alembic `0003_stage4`.
- **api/errors**: `subscription_not_found`, `already_inactive`,
  `node_not_found`.
- **admin**: JWT Bearer auth (sessionStorage `vlessich.admin.jwt`,
  auto-clear on 401 → redirect `/login`). `AuthProvider`, `useAuth`,
  `hasRole(actual, required)` с ranks superadmin>support>readonly.
- **admin**: Spotify-dark design-system — `PillButton` (primary/
  secondary/ghost/danger × sm/md/lg, loading state), `Card`, `Table<T>`
  (generic columns, skeleton rows), `Pagination`, `Modal` (portal +
  backdrop + esc), `Drawer` (side panel), `FormField`, `Input`,
  `Select`, `Textarea`, `StatusBadge` (auto-tone), `RoleBadge`,
  `Toggle`, `SkeletonBlock`, `Sparkline` (SVG latency bars).
- **admin**: typed API client (`lib/api.ts`) с `codes/users/
  subscriptions/audit/nodes/stats` методами, `ApiError {status, code,
  message}`, query-builder.
- **admin/pages**:
  - `Login` — email+password, `POST /admin/auth/login` → sessionStorage.
  - `Dashboard` — node health panel (5 tiles + stacked bar) + 6 metric
    cards, auto-refresh 30s.
  - `Codes` — фильтры status/plan/tag (debounced), pagination, RBAC
    revoke (superadmin), batch create modal с one-time plaintext display
    + "copy all" + warning.
  - `Users` — фильтр tg_id (debounced), link → `/subscriptions?user_id=…`.
  - `Subscriptions` — фильтры status/plan/user_id (URL-synced), revoke
    modal с "type REVOKE" confirmation (support+).
  - `Audit` — фильтры action/actor_type, expandable JSON payload rows.
  - `Nodes` — list + create/edit modals (superadmin), health drawer
    (Sparkline + uptime/p50/p95 + probe log), auto-refresh 15s.
- **admin**: `ProtectedRoute`, `AppShell` (sidebar nav + user email +
  RoleBadge + sign out), nested routes.
- **admin**: vitest + jsdom + @testing-library настройки, tests для
  auth/api/login (не запускаются в CI до `npm install`).

### Changed
- **admin**: Полная переработка `admin/` — удалены placeholder-страницы,
  заменены на production-ready UI по `Design.txt`.
- **admin/README**: описание JWT-аутентификации и RBAC-матрицы вместо
  Cloudflare Access.
- **docs/ARCHITECTURE.md**: §15 Admin UI — стек, auth, RBAC,
  query-keys, design-system inventory.

### Security
- JWT в `sessionStorage` (не `localStorage`) — изоляция от XSS-persistence
  между вкладками и очистка при закрытии браузера.
- Все destructive-действия (revoke code/subscription) требуют
  `type-to-confirm` ввода в модалке.
- RBAC enforced на backend; frontend скрывает кнопки как UX-бонус, не
  security-boundary.

## [0.3.0] — 2026-04-21 — Stage 3: Mini-App Spotify-dark + webapp API

### Added
- **api**: `app/auth/telegram.py` — Telegram `initData` HMAC-SHA256
  verification (TZ §11B). FastAPI dependency `get_init_data` читает
  `x-telegram-initdata` header, валидирует подпись через
  `secret_key = HMAC(b"WebAppData", bot_token)`, проверяет `auth_date`
  ≤ 24h, парсит `user` JSON. Constant-time compare. Unit-тесты покрывают
  valid / bad hash / expired / malformed / missing user.
- **api**: `GET /v1/webapp/bootstrap` — возвращает `{user, subscription}`
  snapshot для главного экрана Mini-App. 404 `user_not_found` если
  пользователь не создан ботом.
- **api**: `GET /v1/webapp/subscription` — детали активной подписки
  (sub_token, urls для 5 клиентов, devices, limits, toggles). Использует
  `services/sub_urls.py::build_sub_urls` + `settings.sub_worker_base_url`.
- **api**: `POST /v1/webapp/subscription/toggle` — обновляет
  `adblock`/`smart_routing`, audit-event `webapp_toggle_routing`. 422
  если ни одно поле не указано.
- **api**: `POST /v1/webapp/devices/{id}/reset` — перегенерирует
  `devices.xray_uuid_enc`, audit `webapp_device_reset`. Rate-limit
  5/min/user через `sliding_window_check`. 403 при попытке сбросить
  чужое устройство.
- **webapp**: Spotify-dark design-system components (`components/`):
  `PillButton` (primary/secondary/ghost), `Card` (+elevated shadow),
  `Toggle` (brand-green active), `StatusBadge` (active/trial/expired),
  `CopyButton`, `QRCodeBlock` (white bg), `SkeletonBlock` (shimmer).
- **webapp**: SWR config + typed API client (`lib/api.ts`) с
  `BootstrapResponse`, `SubscriptionResponse`, `ToggleResponse`,
  `DeviceResetResponse`. `ApiError` с нормализацией `{code, message}`.
- **webapp**: `lib/initData.ts` — helpers `getInitData()`,
  `getStartParam()`, `getTelegramUser()` с dev-fallback на URL query.
- **webapp**: `hooks/useBootstrap.ts`, `hooks/useSubscription.ts` — SWR
  обёртки с dedupe 15–30s + keepPreviousData.
- **webapp**: `lib/deeplinks.ts` — builders для v2rayNG, Clash, sing-box,
  Surge схем импорта subscription URL.
- **webapp**: Страницы переписаны с placeholder'ов на реальные экраны:
  - `HomePage` — `StatusBadge`, план + expiry + CTA (подписка / routing /
    MTProto). Empty state для пользователей без sub.
  - `SubscriptionPage` — QR code + copy, 4 deeplink-кнопки импорта,
    список устройств с confirmation reset flow.
  - `RoutingPage` — два `Toggle` с optimistic SWR mutate + rollback на
    ошибку.
- **webapp**: dependencies: `swr ^2.2.5`, `qrcode.react ^3.1.0`.
- **api/schemas**: `WebappBootstrapOut`, `WebappSubscriptionOut`,
  `WebappToggleIn`, `WebappDeviceResetOut`, `WebappDeviceOut`.
- **api/errors**: новые коды `bad_init_data`, `init_data_expired`,
  `bot_token_not_configured`, `user_not_found`, `forbidden`.
- **api/config**: `sub_worker_base_url` setting (`API_SUB_WORKER_BASE_URL`).

### Changed
- **api**: `/v1/webapp/bootstrap` перенесён из `routers/public.py`
  (был stub) в новый `routers/webapp.py` с реальной auth. `public.py`
  оставлен как namespace для будущих unauth endpoints.
- **webapp**: `App.tsx` обёрнут в `SWRConfig` с retry 3x / 2s
  backoff / revalidateOnFocus.

### Tests
- `test_telegram_initdata.py` — 9 тестов: happy path, missing/bad hash,
  expired, bad auth_date, missing user, malformed JSON, optional fields.
- `test_webapp_bootstrap.py` — 3 теста через `dependency_overrides`.
- `test_webapp_subscription.py` — 2 теста.
- `test_webapp_actions.py` — 6 тестов (toggle validation / update /
  no-sub / reset owner-mismatch / reset ok / rate-limited).
- `test_sub_urls.py` — 3 теста на builder.

### Security
- Constant-time HMAC compare через `hmac.compare_digest`.
- `bot_token` маскируется через `SecretStr`.
- Reset device возвращает только последние 4 символа нового UUID.
- Rate-limit reset-device 5/min/user.
- initData верифицируется на backend; клиент не доверяется.

### Notes
- Тесты написаны, но не запускались локально (Windows без MSVC для
  `pynacl`). AST verified на всех новых Python-файлах.
- TypeScript не компилировался (node не установлен). Code ревьюился на
  tsc-compliance вручную.


## [0.2.0] — 2026-04-21 — Stage 2: Edge + Remnawave HTTP + Admin API

### Added
- **api**: `GET /internal/sub/{token}` — реальная реализация. Lookup по
  `subscriptions.sub_url_token` (ACTIVE/TRIAL), проверка expiry,
  возвращает payload с `inbounds[]` + `meta`. HMAC wire-format
  унифицирован с bot↔api (`METHOD\npath\nts\n` + raw_body).
- **api**: `app/services/sub_payload.py` — composer `build_payload()`
  материализует inbound-список (VLESS+Reality+Vision, VLESS+Reality+XHTTP)
  из subscription + devices + node с расшифровкой `xray_uuid` через
  libsodium secretbox.
- **api**: `HTTPRemnawaveClient` — реальный httpx клиент за тем же
  `RemnawaveClient` ABC, retry 3x exp-backoff на 5xx/timeout. DI-switch
  через `settings.remnawave_mode` (`mock|http`). Контрактные тесты
  (`respx`) на обе реализации.
- **api**: Admin API skeleton — JWT (HS256) + bcrypt password hashing,
  RBAC (superadmin/support/readonly):
  - `POST /admin/auth/login` — rate-limited по email (10/мин) через
    Redis sliding-window, audit в `admin_login_attempts`.
  - `GET/POST/DELETE /admin/codes` — list (filter+pagination) / batch
    create (генерит plaintexts, шифрует `code_enc` + `code_hash`) /
    revoke (superadmin only).
  - `GET /admin/users` — list+filter по `tg_id`.
  - `GET /admin/subscriptions` — list+filter по status/plan/user_id.
  - `GET /admin/audit` — выборка audit_log.
  - `GET/POST/PATCH /admin/nodes` — nodes management (superadmin для
    mutating операций).
- **api**: `app/auth/admin.py` — `hash_password`, `verify_password`,
  `create_access_token`, `decode_token`, `require_admin_role(*roles)`
  dependency factory.
- **api**: Alembic `0002_admin.py` — `admin_users` (id, email citext
  unique, password_hash, role, status, last_login_at) +
  `admin_login_attempts` (email, success, ip_hash, at) с индексом на
  `(email, at)`.
- **api**: settings `remnawave_mode`, `admin_jwt_secret`,
  `admin_jwt_ttl_sec`, `admin_bcrypt_cost`. Dependency добавлены:
  `bcrypt>=4.2`, `pyjwt>=2.9`, `respx>=0.21` (dev).
- **infra**: `infra/workers/subscription.js` — HMAC подпись запроса
  к backend переведена на единый формат (`GET\npath\nts\n`).
- **infra**: `wrangler.subscription.toml` + `wrangler.doh.toml` для
  локальной отладки `wrangler dev` / CI `deploy --dry-run`.
- **tests**: `test_sub_endpoint.py`, `test_sub_payload.py`,
  `test_remnawave_contract.py` (mock+http via respx),
  `test_admin_auth.py`, `test_admin_rbac.py`,
  `test_admin_flows_integration.py` (opt-in, требует
  `VLESSICH_INTEGRATION_DB`).

### Changed
- **infra**: `cloudflare.tf` Pages build_command: `pnpm install` →
  `npm ci && npm run build` для webapp+admin (consistency со Stage 0 T6).
- **api**: `app/ratelimit.py::sliding_window_check` — generic INCR+EXPIRE
  для любых per-key rate limit'ов (используется в admin login).

### Notes
- Stage 2 non-negotiables пройдены: 0 `# type: ignore` / `as any`
  (проверено AST-aware grep по 68 .py файлам); все admin-endpoint'ы
  за RBAC dependency и пишут audit_log; JWT secret/remnawave token —
  `SecretStr`; payload composer не логирует расшифрованные UUID.
- HTTP Remnawave endpoint-shape отражает обобщённый Remnawave REST API
  (`POST /api/users`, `PATCH .../extend`, `DELETE .../users/{id}`,
  `GET .../sub-url`) — patch в один файл при финализации провайдера.
- Wrangler deploy не выполнялся (нет node локально); integration-тесты
  сабворкера требуют Redis+Postgres, поэтому skip по default.

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
