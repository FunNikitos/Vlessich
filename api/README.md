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
- `python -m app.workers.mtproto_rotator` — cron auto-rotation shared
  MTProto секрета (Stage 10, off by default; см. ARCHITECTURE §22).
- `python -m app.workers.mtproto_broadcaster` — DM broadcaster новых
  deeplink'ов после ротации (Stage 10, off by default).

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
| `POST /admin/mtproto/rotate`      | JWT superadmin | Ротация shared MTProto-секрета (Stage 8)        |
| `POST /admin/mtproto/pool/bootstrap`     | JWT superadmin | Pre-seed FREE per-user pool (Stage 9, idempotent)            |
| `GET  /admin/mtproto/pool/config`        | JWT superadmin | Dump FREE+ACTIVE для regen mtg config                        |
| `POST /admin/mtproto/users/{uid}/rotate` | JWT superadmin | REVOKE + claim fresh FREE (Stage 9, gated)                   |
| `POST /admin/mtproto/users/{uid}/revoke` | JWT superadmin | Mark ACTIVE → REVOKED                                         |
| `GET  /admin/mtproto/users`              | JWT readonly+  | Paginated per-user list (metadata only)                       |
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
| `API_MTG_SHARED_SECRET_HEX` | — | Seed для shared MTProto-пула (32 hex lowercase). Unset → пул не сидится; rotate всё равно работает. |
| `API_MTG_SHARED_CLOAK` | `www.microsoft.com` | Fake-TLS cloak domain для shared секрета. Используется seed'ом и rotate-endpoint'ом по умолчанию. |
| `API_MTG_HOST` | `mtp.example.com` | Host в `tg://proxy` deeplink'ах. |
| `API_MTG_PORT` | `443` | Port в `tg://proxy` deeplink'ах. |
| `API_MTG_PER_USER_ENABLED` | `false` | Stage 9 feature gate. Off → `/internal/mtproto/issue scope='user'` → 501 `per_user_disabled`. On → allocator берёт FREE из pool, 503 `pool_full` если пусто. |
| `API_MTG_PER_USER_POOL_SIZE` | `16` | Default `count` для `/admin/mtproto/pool/bootstrap` (1..512). |
| `API_MTG_PER_USER_PORT_BASE` | `8443` | Default `port_base` для bootstrap (1..65535). Pool занимает `[port_base, port_base + pool_size)`. |
| `API_MTG_AUTO_ROTATION_ENABLED` | `false` | Stage 10 cron-rotator master flag. Off → rotator работает, но только обновляет gauge. On → ротирует ACTIVE shared при возрасте ≥ `MTG_SHARED_ROTATION_DAYS`. |
| `API_MTG_SHARED_ROTATION_DAYS` | `30` | Порог возраста (дни) для авто-ротации shared. |
| `API_MTG_ROTATOR_INTERVAL_SEC` | `3600` | Период tick'ов `mtproto_rotator`. |
| `API_MTG_BROADCAST_ENABLED` | `false` | Stage 10 broadcaster master flag. Off → emit + consume no-op (контейнер idle). On → admin/rotator emit'ят в Redis stream, broadcaster DM'ит затронутых юзеров через bot endpoint. |
| `API_MTG_BROADCAST_COOLDOWN_SEC` | `3600` | Минимум секунд между двумя DM одному tg_id. |
| `API_MTG_BROADCAST_IDEMPOTENCY_TTL_SEC` | `86400` | TTL `(event_id, tg_id)` idempotency маркера. |
| `API_MTG_BROADCAST_RL_GLOBAL_PER_SEC` | `30` | Глобальный rate-limit (Telegram ceiling 30 msg/s). |
| `API_MTG_BROADCAST_RL_PER_CHAT_SEC` | `1` | Минимум секунд между сообщениями одному чату. |
| `API_MTG_BROADCAST_STREAM_MAXLEN` | `10000` | Approximate MAXLEN для `mtproto:rotated` XADD. |
| `API_MTG_BROADCAST_BOT_NOTIFY_URL` | `http://bot:8081/internal/notify/mtproto_rotated` | Bot endpoint для HMAC POST. |

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
