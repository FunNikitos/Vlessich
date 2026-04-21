# Vlessich

Telegram-bot VPN-as-a-Service для РФ. Anti-DPI meta 2025–2026: Reality + XHTTP
H3/H2 + Vision + Hysteria2, отдельный MTProto для Telegram через mtg (Fake-TLS).
Control-plane в Cloudflare + финская нода (Helsinki).

📄 **Полное ТЗ**: [`TZ.md`](./TZ.md)
🎨 **Дизайн**: [`Design.txt`](./Design.txt) (Spotify-dark, строго)
🤖 **Master-prompt для ИИ**: [`PROMPT.md`](./PROMPT.md)

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

## Dev quickstart

```bash
# 1. Секреты
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
```

## API surface

| Path                              | Auth        | Назначение                                      |
|-----------------------------------|-------------|-------------------------------------------------|
| `GET /healthz`, `GET /readyz`     | —           | k8s/docker probes                               |
| `GET /metrics`                    | —           | Prometheus (http/admin/subscription, §17)       |
| `POST /internal/codes/activate`   | HMAC (§11A) | Активация кода (из бота)                        |
| `POST /internal/trials`           | HMAC        | Выдача триала                                   |
| `POST /internal/mtproto/issue`    | HMAC        | Выдача MTProto-секрета                          |
| `GET  /internal/sub/{token}`      | HMAC        | sub-Worker → backend (inbounds[] payload)       |
| `POST /admin/auth/login`          | —           | Admin JWT login                                 |
| `GET  /admin/stats`               | JWT         | Dashboard сводка (users/codes/subs/nodes)       |
| `/admin/{codes,users,subscriptions,audit,nodes}` | JWT + RBAC | Admin API (Stage 2 + Stage 4)   |
| `POST /admin/subscriptions/{id}/revoke` | JWT support+ | Отзыв подписки                              |
| `GET  /admin/nodes/{id}/health`   | JWT         | Node health: uptime + p50/p95 + probes          |
| `POST /admin/nodes/{id}/rotate`   | JWT superadmin | Подтверждение ротации IP (clear IP + HEALTHY) |
| `GET  /v1/webapp/bootstrap`       | initData    | Mini-App bootstrap (user + sub summary)         |
| `GET  /v1/webapp/subscription`    | initData    | Mini-App: моя подписка + sub-URLs + devices     |
| `POST /v1/webapp/subscription/toggle` | initData | Mini-App: adblock / smart_routing toggle        |
| `POST /v1/webapp/devices/{id}/reset`  | initData | Mini-App: regenerate xray_uuid (RL 5/min)       |

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
- Admin login защищён Cloudflare Turnstile: `API_TURNSTILE_SECRET` на
  бэке + `VITE_TURNSTILE_SITEKEY` на фронте. Unset → dev-mode (off).

## CI

- `ci.yml` — ruff + mypy + pytest (bot/api), tsc build (webapp/admin),
  terraform fmt/validate, ansible-lint.
- `docker.yml` — build & push образов в GHCR на push/tag.
- `security.yml` — gitleaks + trivy (SARIF в GitHub Security).

## Лицензия

Private / proprietary.
