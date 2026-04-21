# Stage 6 — Observability + Admin Captcha

**Версия:** 1.0
**Дата:** 21.04.2026
**Статус:** ⏳ in progress
**Предпосылка:** Stage 5 завершён (ветка `feat/stage-5-probing`,
HEAD `9d4b2c6`). Active prober пишет `NodeHealthProbe`, manual rotate
endpoint работает.
**Ветка:** `feat/stage-6-observability` (от `feat/stage-5-probing`).
**TZ refs:** §14 (безопасность admin — captcha, rate-limit), §15
(observability — Prometheus/Grafana/Loki).

## Утверждённые решения (locked)

### Scope

- **В этом этапе:** Prometheus metrics (API + prober), Cloudflare
  Turnstile captcha на `POST /admin/auth/login`, Grafana dashboard JSON.
- **НЕ в этом этапе:** Residential RU-proxies probe backend (Stage 7),
  Loki/promtail (Stage 7), alerting rules (Stage 7), mtg metrics
  (Stage 8 — нужен сам mtg контейнер).

### Prometheus architecture

- **API** уже экспонирует `GET /metrics` через `prometheus_client.
  generate_latest()`. Расширяем existing endpoint новыми метриками
  (без multiproc — one worker per API replica, устраивает).
- **Prober** поднимает свой собственный `/metrics` на порту
  `probe_metrics_port` (default **9101**) через
  `prometheus_client.start_http_server()`. Отдельный scrape target.
- **Никаких shared registries** между API и prober — разные процессы,
  разные registries.

### Metrics (MVP набор)

**API** (`app/metrics.py`, singleton `Registry`):

| Имя | Тип | Labels | Назначение |
|---|---|---|---|
| `vlessich_http_request_duration_seconds` | Histogram | `method`, `path_template`, `status` | latency HTTP endpoints |
| `vlessich_admin_login_total` | Counter | `result` (`success`/`fail`/`captcha_fail`/`rate_limited`) | admin login outcomes |
| `vlessich_subscription_events_total` | Counter | `event` (`issued`/`revoked`/`expired_auto`) | domain events |

Middleware `MetricsMiddleware` оборачивает каждый request: берёт
`request.scope["route"].path` если маршрут match, иначе `__unknown__`;
статус из response; длительность — `time.perf_counter()`. Метод HTTP —
UPPERCASE.

**Prober** (`app/workers/prober_metrics.py`):

| Имя | Тип | Labels | Назначение |
|---|---|---|---|
| `vlessich_probe_duration_seconds` | Histogram | `ok` (`true`/`false`) | latency probe |
| `vlessich_probe_total` | Counter | `ok` | счётчик probes |
| `vlessich_node_state` | Gauge | `node_id`, `hostname`, `status` | текущее состояние (1.0 если соответствует, 0.0 иначе — one row per node) |
| `vlessich_node_burned_total` | Counter | — | transitions HEALTHY→BURNED |
| `vlessich_node_recovered_total` | Counter | — | transitions BURNED→HEALTHY |

Histogram buckets: default prometheus_client (0.005..10s).

### Admin captcha (Cloudflare Turnstile)

- Provider = **Cloudflare Turnstile** (бесплатный, CF-native, не требует
  браузерного SDK чужого вендора). sitekey на фронте, secret на бэке.
- Env-vars: `API_TURNSTILE_SECRET` (backend, required in prod),
  `ADMIN_TURNSTILE_SITEKEY` (Vite env, frontend). Если `API_
  TURNSTILE_SECRET` пустой → captcha **отключена** (dev-mode).
- Flow:
  1. Frontend рендерит `<Turnstile>` widget, получает `cf_turnstile_
     response` token.
  2. `AdminLoginIn` получает новое **опциональное** поле `captcha_
     token: str | None`.
  3. Backend: если `settings.turnstile_secret` set → **требует** token,
     POST на `https://challenges.cloudflare.com/turnstile/v0/
     siteverify` с `{secret, response, remoteip}`. Fail → 400 `captcha_
     failed`, success=`json.success == True`.
  4. Метрика `admin_login_total{result="captcha_fail"}` инкрементируется.
- **Rate-limit** (уже есть sliding window 10/60s) **остаётся** — captcha
  не замена.
- Verify client: `httpx.AsyncClient` injectable singleton (для тестов —
  моним).

### Grafana

- `infra/grafana/dashboards/vlessich.json` — один dashboard с 6
  panels: HTTP RPS, HTTP p95 latency, admin login outcomes rate, probe
  success rate, node states table, subscription events rate.
- **Без compose-сервиса** в dev (Grafana не нужна локально —
  scrape-конфиг описан в docs).

---

## T-list

- **T1** — Plan (этот файл).
- **T2** — API metrics: `app/metrics.py` (registry + instruments),
  `MetricsMiddleware` в `main.py`, инструментирование `admin/auth/
  login`, `admin/subscriptions/revoke`, `internal/codes/activate` (issued),
  worker reminders (expired_auto).
- **T3** — Prober metrics: `app/workers/prober.py` инстрементация
  (`probe_duration`, `probe_total`, `node_state`, `node_burned/
  recovered`), `start_http_server(port)` в `main()`.
- **T4** — Turnstile captcha: `app/config.py` (+`turnstile_secret`,
  `turnstile_verify_url`), `app/captcha.py` (verify helper с httpx),
  `AdminLoginIn.captcha_token`, интеграция в `admin_login` handler.
  `admin/.env.example` + `.env.example` add sitekey/secret. UI:
  `admin/src/pages/Login.tsx` — условный Turnstile widget (через
  `@marsidev/react-turnstile` **или** минимальный iframe wrapper;
  предпочтём библиотеку).
- **T5** — Grafana dashboard: `infra/grafana/dashboards/vlessich.json`
  (6 panels, Prometheus datasource placeholder). `infra/grafana/
  README.md` — как импортировать.
- **T6** — Tests:
  - `api/tests/test_metrics.py` — `/metrics` содержит новые метрики,
    middleware инкрементирует `http_request_duration_seconds` после
    вызова любого endpoint.
  - `api/tests/test_admin_login_captcha.py` — fake httpx: token valid →
    200, invalid → 400 `captcha_failed`, no secret → token ignored.
  - `api/tests/test_prober_metrics.py` — после probe увеличивается
    `probe_total`, при BURN растёт `node_burned_total`.
- **T7** — Docs: CHANGELOG `[0.6.0]`, ARCHITECTURE §17 «Observability»,
  root README (метрики + turnstile env), api/README + admin/README.

---

## Acceptance criteria

- [ ] `GET /metrics` содержит `vlessich_http_request_duration_seconds`,
      `vlessich_admin_login_total`, `vlessich_subscription_events_total`.
- [ ] Prober процесс отвечает на `http://prober:9101/metrics` с
      `vlessich_probe_*` и `vlessich_node_state`.
- [ ] Admin login без captcha token (когда secret set) → 400
      `captcha_failed`.
- [ ] Admin login с invalid token → 400, метрика captcha_fail +1.
- [ ] Admin login без secret (dev) → token игнорируется.
- [ ] Grafana JSON валиден (parse успешен).
- [ ] Все новые `.py` парсятся AST. `admin/src/` чист от `as any`.
- [ ] CHANGELOG, ARCHITECTURE §17, README актуализированы.
