# Vlessich

Telegram-bot VPN-as-a-Service для РФ. Anti-DPI meta 2025–2026: Reality + XHTTP
H3/H2 + Vision + Hysteria2, отдельный MTProto для Telegram через mtg (Fake-TLS).
Control-plane в Cloudflare + финская нода (Helsinki).

📄 **Полное ТЗ**: [`TZ.md`](./TZ.md)
🎨 **Дизайн**: [`Design.txt`](./Design.txt) (Spotify-dark, строго)
🤖 **Master-prompt для ИИ**: [`PROMPT.md`](./PROMPT.md)
🚀 **Установка на Ubuntu VPS**: [`docs/DEPLOY-UBUNTU.md`](./docs/DEPLOY-UBUNTU.md) (one-liner)

## Монорепозиторий

```
bot/                — aiogram 3 (Python 3.12)
api/                — FastAPI + PostgreSQL 16 + Redis
webapp/             — Telegram Mini-App (React + Vite + TS + Tailwind)
admin/              — Admin panel (React + Vite + TS + Tailwind)
ansible/            — роль для provisioning FI-ноды
infra/              — Terraform для Cloudflare + Workers (sub, DoH)
caddy/              — HTTPS-фасад FI-ноды
mtg/                — MTProto-прокси конфиг
Makefile            — deploy-node / tf-apply / rotate-mtg-secret / tests
docker-compose.dev.yml
```

## Production quickstart (Ubuntu VPS)

Одна команда на чистой Ubuntu 22.04 / 24.04 (x86_64 / arm64):

```bash
curl -fsSL https://raw.githubusercontent.com/Neikkich/vlessich/main/scripts/install.sh \
  | sudo BOT_TOKEN=123456:ABC... bash
```

Скрипт ставит Docker, клонит репо в `/opt/vlessich`, генерирует все
секреты, поднимает `docker-compose.prod.yml` (all-in-one: bot + api +
postgres + redis + webapp + admin + reminders + prober) и создаёт
superadmin'а. Полный гайд + troubleshooting:
[`docs/DEPLOY-UBUNTU.md`](./docs/DEPLOY-UBUNTU.md).

## Dev quickstart

```bash
cp bot/.env.example bot/.env.dev
cp api/.env.example api/.env.dev
cp webapp/.env.example webapp/.env
cp admin/.env.example admin/.env
# Сгенерировать секреты:
openssl rand -hex 32   # → BOT_API_INTERNAL_SECRET и API_INTERNAL_SECRET (одно и то же)
openssl rand -hex 32   # → API_SECRETBOX_KEY

# 2. Запуск
docker compose -f docker-compose.dev.yml up --build

# 3. Проверка
curl http://localhost:8000/healthz
open http://localhost:5173   # webapp
open http://localhost:5174   # admin
open http://localhost:8025   # mailhog UI (SMTP catcher: 127.0.0.1:1025)
# Reminders worker запускается в сервисе `reminders` (api image,
# CMD `python -m app.workers.reminders`); логи: `docker compose logs reminders`.
# Active prober — сервис `prober` (api image, `python -m app.workers.prober`);
# каждые 60s TCP-connect на hostname:443 каждой non-MAINTENANCE ноды,
# 3 fails подряд → BURNED, 5 oks подряд → HEALTHY (см. ARCHITECTURE §16).
# Prober также экспонирует Prometheus metrics на 127.0.0.1:9101/metrics.
# MTProto (mtg) — сервис `mtg` (nineseconds/mtg:2, :8443 + 127.0.0.1:9410/metrics).
# Shared-секрет сидится из API_MTG_SHARED_SECRET_HEX при старте API
# (идемпотентно). Ротация: POST /admin/mtproto/rotate (superadmin) →
# положить config_line из ответа в mtg/config.toml и `docker compose restart mtg`.
# Per-user MTProto (Stage 9): pre-seeded FREE-pool. Сначала
# `docker compose --profile per-user-mtg up` поднимает 4 mtg-контейнера
# (8444..8447). Bootstrap пула:
#   curl -X POST http://localhost:8000/admin/mtproto/pool/bootstrap \
#     -H "Authorization: Bearer $JWT" -H "content-type: application/json" \
#     -d '{"count":4,"port_base":8444}'
# Скармливаешь `items` в `./mtg/pool/{port}.toml` (см. mtg/README.md),
# ставишь API_MTG_PER_USER_ENABLED=true, перезапускаешь api.
# Stage 10 workers: `mtproto_rotator` (port 9102) и
# `mtproto_broadcaster` (port 9103) поднимаются вместе с api; оба
# master flags (API_MTG_AUTO_ROTATION_ENABLED / API_MTG_BROADCAST_ENABLED)
# ship off. Rotator всё равно обновляет gauge
# vlessich_mtproto_shared_secret_age_seconds на :9102. Bot endpoint
# /internal/notify/mtproto_rotated слушает на порту 8081 (см. bot/.env).
# Stage 12 ruleset puller: `ruleset_puller` (port 9104, off by default).
# Master-flags: API_SMART_ROUTING_ENABLED (endpoint), API_RULESET_PULLER_ENABLED
# (worker), BOT_SMART_ROUTING_ENABLED (bot UI). Default sources (antifilter +
# v2fly category-ru + category-ads-all + custom) сидятся в lifespan
# идемпотентно. Bot `/config` отдаёт 4 профиля (full/smart/adblock/plain),
# `Subscription.routing_profile` — single source of truth. См.
# `docs/ARCHITECTURE.md` §24.
```

## API surface

| Path                              | Auth        | Назначение                                      |
|-----------------------------------|-------------|-------------------------------------------------|
| `GET /healthz`, `GET /readyz`     | —           | k8s/docker probes                               |
| `GET /metrics`                    | —           | Prometheus (http/admin/subscription, §17)       |
| `POST /internal/codes/activate`   | HMAC (§11A) | Активация кода (из бота)                        |
| `POST /internal/trials`           | HMAC        | Выдача триала                                   |
| `POST /internal/mtproto/issue`    | HMAC        | Выдача MTProto-секрета                          |
| `POST /internal/payments/plans`   | HMAC        | Billing: список активных SKU (Stage 11)         |
| `POST /internal/payments/create_order` | HMAC   | Billing: PENDING order перед send_invoice        |
| `POST /internal/payments/precheck`| HMAC        | Billing: валидация pre_checkout_query            |
| `POST /internal/payments/success` | HMAC        | Billing: финализация successful_payment          |
| `GET  /internal/sub/{token}`      | HMAC        | sub-Worker → backend (inbounds[] payload)       |
| `POST /admin/auth/login`          | —           | Admin JWT login                                 |
| `GET  /admin/stats`               | JWT         | Dashboard сводка (users/codes/subs/nodes)       |
| `/admin/{codes,users,subscriptions,audit,nodes}` | JWT + RBAC | Admin API (Stage 2 + Stage 4)   |
| `POST /admin/subscriptions/{id}/revoke` | JWT support+ | Отзыв подписки                              |
| `GET  /admin/nodes/{id}/health`   | JWT         | Node health: uptime + p50/p95 + probes          |
| `POST /admin/nodes/{id}/rotate`   | JWT superadmin | Подтверждение ротации IP (clear IP + HEALTHY) |
| `POST /admin/mtproto/rotate`      | JWT superadmin | Ротация shared MTProto-секрета (Stage 8)        |
| `POST /admin/mtproto/pool/bootstrap`     | JWT superadmin | Pre-seed FREE per-user MTProto pool (Stage 9, idempotent)  |
| `GET  /admin/mtproto/pool/config`        | JWT superadmin | Dump FREE+ACTIVE per-user secrets для regen mtg config     |
| `POST /admin/mtproto/users/{uid}/rotate` | JWT superadmin | REVOKE + claim fresh FREE per-user секрет (Stage 9, gated) |
| `POST /admin/mtproto/users/{uid}/revoke` | JWT superadmin | Mark per-user ACTIVE → REVOKED                              |
| `GET  /admin/mtproto/users`              | JWT readonly+  | Paginated per-user secrets list (metadata only)             |
| `GET  /admin/orders`                     | JWT readonly+  | Stage 11: list orders (filters: status, user_id)             |
| `GET  /admin/orders/{id}`                | JWT readonly+  | Stage 11: order detail                                       |
| `POST /admin/orders/{id}/refund`         | JWT superadmin | Stage 11: two-phase refund (bot HMAC push + DB transition)  |
| `GET  /v1/webapp/bootstrap`       | initData    | Mini-App bootstrap (user + sub summary)         |
| `GET  /v1/webapp/subscription`    | initData    | Mini-App: моя подписка + sub-URLs + devices     |
| `POST /v1/webapp/subscription/toggle` | initData | Mini-App: adblock / smart_routing toggle        |
| `POST /v1/webapp/devices/{id}/reset`  | initData | Mini-App: regenerate xray_uuid (RL 5/min)       |
| `GET  /internal/smart_routing/config`     | HMAC          | Stage 12: ruleset payload (singbox JSON + clash YAML) |
| `POST /internal/smart_routing/set_profile`| HMAC          | Stage 12: bot → set routing_profile (full/smart/adblock/plain) |
| `GET  /admin/ruleset/sources`             | JWT readonly+ | Stage 12: list ruleset sources                              |
| `POST /admin/ruleset/sources`             | JWT super     | Stage 12: create/upsert source                              |
| `PATCH /admin/ruleset/sources/{id}`       | JWT super     | Stage 12: toggle is_enabled / edit URL                      |
| `GET  /admin/ruleset/snapshots`           | JWT readonly+ | Stage 12: list recent snapshots                             |
| `POST /admin/ruleset/pull`                | JWT super     | Stage 12: force-pull all enabled sources                    |

## Prod deploy

1. `cd infra && sops -d terraform.tfvars.enc > terraform.tfvars && terraform apply` —
   поднимет DNS, Pages, Workers, Access, WAF.
2. `make deploy-node HOST=fi-01.example.com` — Ansible провизионит ноду (Xray
   + AGH + Caddy + mtg + nftables + fwknop).
3. Публикация Docker-образов в GHCR через CI (`.github/workflows/docker.yml`).

## Non-negotiables

- **No PII in logs**: только `sha256(ip + IP_SALT)`.
- **No type escapes**: запрещены `as any`, `@ts-ignore`, `# type: ignore`,
  пустые `except:`/`catch`.
- **Dark only**: Mini-App и Admin — строго по `Design.txt` (Spotify-dark).
- **HMAC на internal endpoints**: бот ↔ API и sub-Worker ↔ API подписывают
  запросы `x-vlessich-sig` (SHA-256, clock skew ≤60s).

## Observability

- API `/metrics` + prober `/metrics` (port 9101) — Prometheus.
- Grafana dashboard: `infra/grafana/dashboards/vlessich.json`
  (import в Grafana UI). Scrape-config см. `infra/grafana/README.md`.
- Alert rules: `infra/prometheus/rules/vlessich.yml`
  (NodeBurnSpike / ProbeSuccessLow / ProberDown / ApiP95Latency /
  AdminCaptchaFailSpike). Alertmanager wiring — deploy-time.
- Log aggregation: Loki + promtail (`infra/loki/`, single-binary,
  structlog JSON, labels `service/level/logger/env`). См.
  `infra/loki/README.md`.
- Residential RU probing (Stage 7): prober запускает второй backend
  (`ru`) через `API_RU_PROXY_URL` — telemetry only, не зажигает BURN.
  `NodeHealthProbe.probe_source ∈ {edge, ru}`.
- Admin login защищён Cloudflare Turnstile: `API_TURNSTILE_SECRET` на
  бэке + `VITE_TURNSTILE_SITEKEY` на фронте. Unset → dev-mode (off).

## CI

- `ci.yml` — ruff + mypy + pytest (bot/api), tsc build (webapp/admin),
  terraform fmt/validate, ansible-lint.
- `docker.yml` — build & push образов в GHCR на push/tag.
- `security.yml` — gitleaks + trivy (SARIF в GitHub Security).

## Лицензия

Private / proprietary.
