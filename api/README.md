# Vlessich — Backend API (FastAPI)

Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL 16 · Alembic.

## Dev

```bash
cp .env.example .env.dev
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

## Workers

- `python -m app.workers.reminders` — напоминания об окончании подписки.
- `python -m app.workers.prober` — active probing + BURN/RECOVER state
  machine (см. `docs/ARCHITECTURE.md` §16).

## Endpoints

| Path                              | Auth        | Назначение                                      |
|-----------------------------------|-------------|-------------------------------------------------|
| `GET /healthz`, `GET /readyz`     | —           | k8s/docker probes                               |
| `GET /metrics`                    | —           | Prometheus                                      |
| `POST /internal/codes/activate`   | HMAC (§11A) | Активация кода (из бота)                        |
| `POST /internal/trials`           | HMAC        | Выдача триала                                   |
| `POST /internal/mtproto/issue`    | HMAC        | Выдача MTProto-секрета                          |
| `GET  /internal/sub/{token}`      | HMAC        | sub-Worker → backend (edge subscription)        |
| `POST /admin/auth/login`          | —           | Admin JWT login                                 |
| `GET  /admin/stats`               | JWT         | Dashboard сводка                                |
| `/admin/{codes,users,subscriptions,audit,nodes}` | JWT + RBAC | Admin CRUD / RO               |
| `POST /admin/subscriptions/{id}/revoke` | JWT support+ | Отзыв подписки                              |
| `GET  /admin/nodes/{id}/health`   | JWT         | uptime 24h + p50/p95 latency + last 50 probes   |
| `POST /admin/nodes/{id}/rotate`   | JWT superadmin | Подтверждение ротации IP (clear IP + HEALTHY) |
| `GET  /v1/webapp/bootstrap`       | initData    | Mini-App bootstrap                              |
| `GET  /v1/webapp/subscription`    | initData    | Mini-App: подписка + sub-URLs + devices         |
| `POST /v1/webapp/subscription/toggle` | initData | adblock / smart_routing toggle                  |
| `POST /v1/webapp/devices/{id}/reset`  | initData | regenerate xray_uuid (RL 5/min)                 |

## Settings (env `API_*`)

| Env | Default | Назначение |
|---|---|---|
| `API_INTERNAL_SECRET` | — | HMAC ключ для `/internal/*` |
| `API_SECRETBOX_KEY` | — | libsodium secretbox для codes/xray_uuid |
| `API_JWT_SECRET` | — | HS256 admin JWT |
| `API_PROBE_INTERVAL_SEC` | `60` | Интервал `prober` цикла |
| `API_PROBE_TIMEOUT_SEC` | `5` | Таймаут одного TCP-probe |
| `API_PROBE_PORT` | `443` | Порт для probe |
| `API_PROBE_BURN_THRESHOLD` | `3` | Fails подряд → `BURNED` |
| `API_PROBE_RECOVER_THRESHOLD` | `5` | Oks подряд → `HEALTHY` |
| `API_PROBE_METRICS_PORT` | `9101` | Порт `/metrics` prober |
| `API_RU_PROXY_URL` | — | Residential RU proxy URL (unset → RU backend отключён). SOCKS5/HTTP, например `socks5://user:pass@host:1080`. |
| `API_RU_PROBE_TIMEOUT_SEC` | `8` | Таймаут одного HTTP-probe через RU прокси |
| `API_TURNSTILE_SECRET` | — | Cloudflare Turnstile secret (unset = captcha off, dev) |
| `API_TURNSTILE_VERIFY_URL` | `https://challenges.cloudflare.com/turnstile/v0/siteverify` | Siteverify endpoint |

## Миграции

```bash
alembic revision -m "init" --autogenerate
alembic upgrade head
```

## Security

- Internal endpoints требуют HMAC-SHA256 подписи (header `x-vlessich-sig`),
  clock skew ≤60s. Ключ `API_INTERNAL_SECRET` общий с ботом и sub-Worker.
- Xray UUID и activation-коды хранятся зашифрованными (libsodium
  secretbox, `API_SECRETBOX_KEY`).
- Admin JWT TTL = 1h, без refresh-токенов.
- Admin login защищён Cloudflare Turnstile (`API_TURNSTILE_SECRET`).
  Если secret unset → captcha off (dev). Rate-limit (10/60s per email)
  остаётся независимо.
- PII не логируется (IP только как `sha256(ip + IP_SALT)`).
