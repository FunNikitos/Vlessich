# Vlessich — деплой на Ubuntu (one-liner)

Гайд для развёртывания **all-in-one** стека Vlessich на чистой
Ubuntu-VPS. Один скрипт ставит Docker, клонит репозиторий, генерирует
секреты и поднимает сервисы.

> **Топология:** control-plane (bot + api + postgres + redis + webapp +
> admin) и опциональные workers — **на одной машине**. Это самый простой
> вариант для small-prod / dev / демо. Для продакшена с разделением
> control-plane и FI-ноды используйте `make deploy-node` (Ansible) — см.
> `ansible/README.md`.

---

## 1. Требования

| Что | Минимум | Рекомендуется |
|---|---|---|
| ОС  | Ubuntu **22.04** или **24.04** | Ubuntu 24.04 LTS |
| Архитектура | x86_64 (amd64) или aarch64 (arm64) | x86_64 |
| RAM | 2 GB | 4 GB |
| Диск | 20 GB free | 40 GB SSD |
| Сеть | Открытый исходящий 443/80 | + входящий 443 если будете ставить TLS |
| Доступ | root через `sudo` | + публичное доменное имя |

Перед стартом нужно:

1. **Bot token** — создать бота у [@BotFather](https://t.me/BotFather)
   и сохранить токен (формат `123456:ABC-DEF…`).
2. **(Опционально) домен** — если хотите webhook + публичный HTTPS,
   подготовьте A-запись на IP сервера.

---

## 2. One-liner установка

Подключаемся к серверу по SSH и запускаем:

```bash
curl -fsSL https://raw.githubusercontent.com/Neikkich/vlessich/main/scripts/install.sh \
  | sudo BOT_TOKEN=123456:ABC_DEF... bash
```

Скрипт спросит (если не передали через env):

* `BOT_TOKEN` — токен бота от BotFather (**обязательно**).
* `PUBLIC_DOMAIN` — например `vlessich.example.com` (опционально, оставьте
  пустым → бот будет в polling-режиме).
* `ADMIN_EMAIL` — почта для входа в админку (по умолчанию
  `admin@localhost`).

В конце скрипт распечатает:

```
Vlessich is up
─────────────────────────────────────
  install dir : /opt/vlessich
  bot         : @your_bot
  api         : http://127.0.0.1:8000
  webapp      : http://127.0.0.1:5173
  admin UI    : http://127.0.0.1:5174

  Admin login
    email    : admin@localhost
    password : Xa9k...auto-generated...Q3
```

**Готово.** Бот в Telegram уже отвечает на `/start`.

---

## 3. Что делает install.sh

1. Проверяет ОС (Ubuntu 22.04/24.04), архитектуру, занятые порты.
2. Ставит apt-зависимости (`curl gnupg openssl git iproute2 jq`).
3. Ставит Docker через официальный `get.docker.com` (если ещё нет).
4. Клонит репо в `/opt/vlessich` (или обновляет `git pull --ff-only`).
5. Генерирует секреты в `/opt/vlessich/.secrets/` (`chmod 600`):
   * `api_internal_secret`, `api_secretbox_key`, `api_jwt_secret`,
     `pg_password` — `openssl rand -hex 32`,
   * `admin_password` — `openssl rand -base64 24`.
6. Спрашивает `BOT_TOKEN` / `PUBLIC_DOMAIN` / `ADMIN_EMAIL`.
7. Рендерит `.secrets/{db,api,bot}.env` из шаблонов.
8. `docker compose -f docker-compose.prod.yml up -d --build`,
   ждёт `healthz` API.
9. Создаёт superadmin через `python -m app.scripts.create_admin`
   (идемпотентно — если уже есть, пропускает).
10. Печатает итоговый отчёт.

**Идемпотентность.** Повторный запуск `install.sh`:

* пропускает уже сгенерированные секреты;
* `git pull --ff-only` обновляет код;
* пересобирает образы и перезапускает изменившиеся сервисы;
* admin не пересоздаёт.

---

## 4. Доступ к админке и Mini-App

Веб-интерфейсы биндятся **только** на `127.0.0.1` (для безопасности).
Чтобы открыть с локальной машины — SSH-туннель:

```bash
ssh -L 5174:127.0.0.1:5174 -L 5173:127.0.0.1:5173 -L 8000:127.0.0.1:8000 \
    user@your-server.example.com
```

Затем в браузере:

* админка → http://localhost:5174
* webapp → http://localhost:5173
* API healthz → http://localhost:8000/healthz

Логин в админку — `ADMIN_EMAIL` + пароль из финального отчёта (или
`/opt/vlessich/.secrets/admin_password`).

### Хочу публичный HTTPS

Поставьте Caddy или nginx перед стеком:

```bash
sudo apt install -y caddy
```

Минимальный `/etc/caddy/Caddyfile`:

```
your-domain.example.com {
    reverse_proxy /telegram/webhook 127.0.0.1:8000
    reverse_proxy /v1/* 127.0.0.1:8000
    reverse_proxy /healthz 127.0.0.1:8000
    reverse_proxy /metrics 127.0.0.1:8000
    reverse_proxy /admin/* 127.0.0.1:8000
    reverse_proxy /internal/* 127.0.0.1:8000
}

admin.your-domain.example.com {
    reverse_proxy 127.0.0.1:5174
}

app.your-domain.example.com {
    reverse_proxy 127.0.0.1:5173
}
```

`sudo systemctl reload caddy` — TLS-сертификаты Let's Encrypt подтянутся
автоматически.

После этого включите webhook:

```bash
curl -X POST "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
     -d "url=https://your-domain.example.com/telegram/webhook" \
     -d "secret_token=$(grep BOT_WEBHOOK_SECRET /opt/vlessich/.secrets/bot.env | cut -d= -f2)"
```

---

## 5. Опциональные профили

По умолчанию запускается минимум: `db redis api bot reminders prober
webapp admin`. Дополнительно:

```bash
# MTProto (mtg + auto-rotation + broadcaster)
sudo VLESSICH_PROFILES=mtproto bash /opt/vlessich/scripts/install.sh

# Ruleset puller (smart-routing, RU lists, ads)
sudo VLESSICH_PROFILES=ruleset bash /opt/vlessich/scripts/install.sh

# Оба сразу
sudo VLESSICH_PROFILES=mtproto,ruleset bash /opt/vlessich/scripts/install.sh
```

Не забудьте включить master-flags в `.secrets/api.env`:

* `API_MTG_AUTO_ROTATION_ENABLED=true` для ротатора,
* `API_MTG_BROADCAST_ENABLED=true` для broadcaster'а,
* `API_RULESET_PULLER_ENABLED=true` для ruleset puller,
* `API_SMART_ROUTING_ENABLED=true` для endpoint'а smart routing.

После правки — `docker compose -f docker-compose.prod.yml restart api`.

---

## 6. Управление стеком

Все команды — из `/opt/vlessich`:

```bash
cd /opt/vlessich

# статус
docker compose -f docker-compose.prod.yml ps

# логи
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f bot

# рестарт сервиса
docker compose -f docker-compose.prod.yml restart api bot

# полная остановка
docker compose -f docker-compose.prod.yml down

# полный запуск (после правок .env / docker-compose)
docker compose -f docker-compose.prod.yml up -d --build
```

### Обновление до свежего main

```bash
sudo bash /opt/vlessich/scripts/install.sh
```

`install.sh` повторно безопасен — секреты не перегенерируются,
admin не пересоздаётся, просто `git pull` + `compose up -d --build`.

### Бэкап БД

```bash
docker compose -f docker-compose.prod.yml exec -T db \
    pg_dump -U vlessich -d vlessich -Fc > vlessich-$(date +%F).dump
```

Восстановление:

```bash
docker compose -f docker-compose.prod.yml exec -T db \
    pg_restore -U vlessich -d vlessich --clean --if-exists < vlessich-2026-04-22.dump
```

---

## 7. Step-by-step (без one-liner)

Если вы хотите контролировать каждый шаг:

```bash
# 1. apt + docker
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg openssl git jq
curl -fsSL https://get.docker.com | sudo sh

# 2. клон репо
sudo mkdir -p /opt
sudo git clone https://github.com/Neikkich/vlessich.git /opt/vlessich
cd /opt/vlessich

# 3. секреты
sudo mkdir -p .secrets
sudo chmod 700 .secrets
for f in api_internal_secret api_secretbox_key api_jwt_secret pg_password; do
    sudo sh -c "openssl rand -hex 32 > .secrets/$f"
    sudo chmod 600 .secrets/$f
done
sudo sh -c "openssl rand -base64 24 | tr -d '/+=' | head -c 24 > .secrets/admin_password"
sudo chmod 600 .secrets/admin_password

# 4. ручное заполнение .secrets/{db,api,bot}.env
# (см. шаг 7 в scripts/install.sh — тот же шаблон)

# 5. поднять
sudo docker compose -f docker-compose.prod.yml up -d --build

# 6. создать admin
sudo docker compose -f docker-compose.prod.yml exec api \
    python -m app.scripts.create_admin \
        --email admin@localhost \
        --password "$(sudo cat .secrets/admin_password)" \
        --role superadmin
```

---

## 8. Troubleshooting

### `docker: command not found` после install.sh
Скрипт добавил вашего пользователя в группу `docker`, но эффект
применяется после re-login. Завершите SSH-сессию и подключитесь снова,
или временно используйте `sudo docker ...`.

### API не становится healthy
Проверьте логи:
```bash
docker compose -f docker-compose.prod.yml logs api | tail -100
```
Чаще всего — миграции не прошли (Postgres ещё не готов). Подождите 30 сек
и `docker compose restart api`.

### Бот не отвечает на /start
1. Убедитесь, что токен валиден:
   ```bash
   curl "https://api.telegram.org/bot${BOT_TOKEN}/getMe"
   ```
2. Если используете webhook — посмотрите `getWebhookInfo`, проверьте,
   что `last_error_message` пуст.
3. Логи:
   `docker compose -f docker-compose.prod.yml logs bot | tail -50`.

### Порт уже занят
```
Error starting userland proxy: bind: address already in use
```
Найти занявший процесс:
```bash
sudo ss -ltnp | grep ':8000'
```
И либо остановить его, либо изменить port mapping в
`docker-compose.prod.yml`.

### Я хочу удалить всё и переустановить
```bash
cd /opt/vlessich
sudo docker compose -f docker-compose.prod.yml down -v
sudo rm -rf /opt/vlessich
# затем заново curl ... | sudo bash
```
**Внимание:** `down -v` удалит volume `pgdata` — все коды/подписки
будут потеряны. Перед этим сделайте бэкап БД (см. §6).

### Невозможно расшифровать старые activation-коды после re-install
Скрипт **никогда** не перегенерирует существующие секреты в
`.secrets/`. Если вы их случайно удалили — старые коды и
`xray_uuid` восстановить нельзя. Восстановите `.secrets/` из бэкапа
или сгенерите подписки заново.

### Webhook отдаёт 404 / 502
Caddy/nginx должен проксировать `/telegram/webhook` на 8000:
```
reverse_proxy /telegram/webhook 127.0.0.1:8000
```
И `BOT_WEBHOOK_URL` в `.secrets/bot.env` должен совпадать с тем, что
вы передали в `setWebhook`.

---

## 9. Безопасность по умолчанию

* **Все web-порты** (api/webapp/admin) биндятся на `127.0.0.1` —
  доступ только через SSH-туннель или reverse-proxy.
* **`.secrets/`** — `chmod 700`, файлы `chmod 600`, в `.gitignore`.
* **Postgres / Redis** — биндятся на `127.0.0.1`, пароль БД генерится
  per-host.
* **Admin password** генерится один раз, печатается финальным отчётом
  и сохраняется в `.secrets/admin_password`.
* **Bot webhook secret** генерится отдельно (если задан
  `PUBLIC_DOMAIN`), нужен в заголовке `X-Telegram-Bot-Api-Secret-Token`.
* **HMAC** между bot ↔ api — общий `API_INTERNAL_SECRET`,
  одинаковый в `api.env` и `bot.env`.

`install.sh` **не настраивает** `ufw` / firewall автоматически
(opinionated). Рекомендую вручную:

```bash
sudo ufw allow 22/tcp
sudo ufw allow 443/tcp     # если ставите Caddy
sudo ufw allow 8443/tcp    # если включён --profile mtproto
sudo ufw enable
```

---

## 10. Что дальше

* Настроить Caddy + публичный домен → §4.
* Включить Telegram Stars billing → `API_BILLING_ENABLED=true` +
  `BOT_BILLING_ENABLED=true` (см. `docs/ARCHITECTURE.md §23`).
* Включить smart-routing профили → `VLESSICH_PROFILES=ruleset` +
  `API_SMART_ROUTING_ENABLED=true` (см. `docs/ARCHITECTURE.md §24`).
* Подключить FI-ноду через `make deploy-node` — `ansible/README.md`.
* Настроить мониторинг (Prometheus + Grafana) — `infra/grafana/README.md`.

---

**Связанные документы:**

* [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) — архитектура (24 секции)
* [`docs/plan-stage-13.md`](./plan-stage-13.md) — план этого этапа
* [`TZ.md`](../TZ.md) — полное ТЗ
* [`CHANGELOG.md`](../CHANGELOG.md) — история релизов
