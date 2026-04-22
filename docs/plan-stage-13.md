# Stage 13 — All-in-one Ubuntu installer

> Цель: Превратить запуск Vlessich на свежей Ubuntu-VPS в **одну команду**.
> Топология — all-in-one (control-plane + опциональный VPN-стек на одной
> машине). Audience: оператор без DevOps-бэкграунда, имеющий только SSH
> к чистой Ubuntu 22.04/24.04.

## DoD

- [ ] `curl -fsSL .../scripts/install.sh | sudo bash` поднимает рабочий
  стек за один проход на чистой Ubuntu 22.04 / 24.04 (x86_64 / arm64).
- [ ] Идемпотентность: повторный запуск не ломает существующий стек,
  не пересоздаёт уже сгенерированные секреты.
- [ ] Все секреты генерируются на машине (`openssl rand -hex 32`),
  никаких placeholder'ов в `.env.prod`.
- [ ] Минимум интерактивных вопросов: только `BOT_TOKEN`,
  `PUBLIC_DOMAIN` (опц.), `ADMIN_EMAIL`. Всё остальное — defaults.
- [ ] После завершения скрипт печатает: admin URL + сгенерированный
  пароль, bot username, webhook URL для setWebhook (если задан домен),
  пути к логам.
- [ ] `docker-compose.prod.yml` поднимает только то, что нужно
  для прод-минимума: db, redis, api, bot, reminders, webapp, admin
  (+ prober как cron-health). Per-user mtg / mtproto_rotator / broadcaster /
  ruleset_puller — opt-in через `--profile`.
- [ ] `docs/DEPLOY-UBUNTU.md` покрывает: prerequisites, one-liner,
  ручной step-by-step, обновление, бэкапы, troubleshooting (FAQ ≥ 5).

## Non-goals

- FI-нода (Xray/AGH/Caddy/mtg на отдельном сервере) — Ansible-роль
  существующая, не трогаем.
- TLS / Let's Encrypt автоматизация — оставляем оператору
  (Caddy/nginx опционально). Default: bot polling (без webhook,
  без публичного HTTPS), webapp/admin доступны на 127.0.0.1
  через SSH-tunnel.
- Multi-node, k8s, terraform.

## Tasks

| # | Type | Описание | Verify |
|---|---|---|---|
| T1 | docs | `plan-stage-13.md` (этот файл) | git log shows commit |
| T2 | feat | `docker-compose.prod.yml` — all-in-one prod-стек, profiles `mtproto-rotator`, `mtproto-broadcaster`, `ruleset-puller`, `mtg-shared` | `docker compose -f ... config` валиден (yaml.safe_load) |
| T3 | feat | `scripts/install.sh` + `scripts/lib/*.sh` (детектор ОС, install docker, gen secrets, render `.env.prod`, `compose up`) | shellcheck (smoke) + idempotency dry-run |
| T4 | docs | `docs/DEPLOY-UBUNTU.md` (quickstart + steps + troubleshooting) + `CHANGELOG.md [0.13.0]` + README pointer | markdown parses, links resolve |

## Дизайн

### `scripts/install.sh` flow

```
sudo bash install.sh
  │
  ├─ 1. Pre-flight
  │    - assert running as root (re-exec через sudo)
  │    - detect Ubuntu 22.04 / 24.04 (lsb_release)
  │    - assert arch x86_64 | aarch64
  │    - check ports 80/443/5432/6379/8000 (warn, не блокирует)
  │
  ├─ 2. apt deps
  │    - apt-get update
  │    - install: ca-certificates curl gnupg openssl git ufw
  │
  ├─ 3. Docker
  │    - if !command -v docker:
  │        official get.docker.com installer
  │        usermod -aG docker $SUDO_USER
  │    - assert docker compose v2 plugin present
  │
  ├─ 4. Repo
  │    - INSTALL_DIR=/opt/vlessich (override via $VLESSICH_DIR)
  │    - if !exists: git clone https://github.com/.../vlessich $DIR
  │    - else: git -C $DIR fetch && git pull --ff-only (warn on diverged)
  │
  ├─ 5. Secrets (idempotent)
  │    - if !$DIR/.secrets/api.env: gen + persist (chmod 600)
  │    - if !$DIR/.secrets/bot.env: gen + persist
  │    - admin password: openssl rand -base64 24, печатаем 1 раз
  │
  ├─ 6. Interactive prompts (skip if env vars set)
  │    - BOT_TOKEN (required, regex /^\d+:[\w-]{30,}$/)
  │    - PUBLIC_DOMAIN (optional, default empty → polling)
  │    - ADMIN_EMAIL (default admin@localhost)
  │
  ├─ 7. Render .env files
  │    - api/.env.prod, bot/.env.prod (через envsubst)
  │
  ├─ 8. Compose up
  │    - docker compose -f docker-compose.prod.yml pull
  │    - docker compose -f docker-compose.prod.yml up -d --build
  │    - wait healthy: db, redis, api (timeout 120s)
  │    - alembic upgrade head — выполнится в api entrypoint
  │
  ├─ 9. Admin bootstrap
  │    - docker compose exec api python -m app.scripts.create_admin
  │      --email $ADMIN_EMAIL --password $ADMIN_PASSWORD --role superadmin
  │    - идемпотентно: skip if admin exists
  │
  └─ 10. Final report
       - admin URL, email, password
       - bot username (через GetMe)
       - webhook setup hint (если PUBLIC_DOMAIN задан)
       - log locations
```

### `docker-compose.prod.yml` shape

* Базовый: `db`, `redis`, `api`, `bot`, `reminders`, `prober`, `webapp`, `admin`.
* Все секреты через `env_file: .secrets/*.env` (вне репозитория).
* `restart: always` (vs dev `unless-stopped`).
* Postgres data в named volume `pgdata`, opt-in bind-mount через
  `VLESSICH_PGDATA_DIR`.
* Profiles:
  * `mtproto`: `mtg` (shared) + `mtproto_rotator` + `mtproto_broadcaster`
  * `ruleset`: `ruleset_puller`
  * `mailhog`: dev SMTP catcher
* Ports binding:
  * `127.0.0.1:8000` (api), `127.0.0.1:5173` (webapp), `127.0.0.1:5174` (admin)
  * `0.0.0.0:8443` (mtg, only with `--profile mtproto`)
  * Postgres/Redis — **только** на `127.0.0.1`.

### Безопасность по умолчанию

* `.secrets/` в .gitignore (новый entry).
* `chmod 700 .secrets/`, `chmod 600 .secrets/*.env`.
* Ports webapp/admin/api не expose'нуты на 0.0.0.0 — оператор
  выбирает: SSH tunnel / Caddy / nginx.
* `ufw` не настраиваем автоматически (opinionated; warn только если
  активен и блокирует docker bridge).

### Анти-фейлы

* Если `BOT_TOKEN` пустой — abort на шаге 6.
* Если повторный запуск с другим `.secrets/api.env` — warn о
  невозможности расшифровать существующие codes; abort если
  `--force-rotate` не передан.
* Если `lsb_release` не Ubuntu 22.04/24.04 — warn + продолжить только
  при `VLESSICH_FORCE_OS=1`.

## Verification (CI отсутствует, локально на Windows — недоступно)

* `bash -n scripts/install.sh` → syntax check.
* `python -c "import yaml; yaml.safe_load(open('docker-compose.prod.yml'))"` → структура валидна.
* Smoke: на чистой Ubuntu 24.04 VPS оператор гоняет `bash install.sh` —
  ручная проверка после деплоя (не в скоупе автотестов).

## Коммиты

```
T1  docs: stage-13 ubuntu installer plan
T2  feat(deploy): stage-13 docker-compose.prod.yml all-in-one
T3  feat(deploy): stage-13 scripts/install.sh + libs (idempotent bootstrap)
T4  docs(stage-13): DEPLOY-UBUNTU.md + CHANGELOG [0.13.0] + README quickstart
```
