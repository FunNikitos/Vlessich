# Vlessich — MTProto-прокси (mtg)

## Что это
MTProto-прокси для Telegram на базе [9seconds/mtg](https://github.com/9seconds/mtg)
с Fake-TLS маскировкой под `www.microsoft.com`. См. TZ §9A.

## Деплой

### Production (рекомендуется — отдельный VPS, см. TZ §9A.8)

```bash
# На отдельной ноде mtp.example.com
docker compose -f docker-compose.yml up -d
```

### docker-compose.yml

```yaml
services:
  mtg:
    image: nineseconds/mtg:2
    restart: unless-stopped
    network_mode: host           # для прямой работы на :8443
    volumes:
      - ./config.toml:/config.toml:ro
    command: ["run", "/config.toml"]
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:9410/metrics"]
      interval: 30s
      timeout: 5s
      retries: 3
```

## Генерация секрета

```bash
docker run --rm nineseconds/mtg:2 generate-secret www.microsoft.com
# → ee367a189bef60a91e1cccdfc7d31eb27777772e6d6963726f736f66742e636f6d
```

Где формат: `ee` + 32 hex (рандом) + hex(cloak-домен).

## Получение deep-link для пользователя

```bash
docker run --rm -v $(pwd)/config.toml:/c.toml nineseconds/mtg:2 access /c.toml
```

Выдаст URL вида:
```
tg://proxy?server=mtp.example.com&port=8443&secret=ee367a...
https://t.me/proxy?server=mtp.example.com&port=8443&secret=ee367a...
```

## Ротация секрета (раз в 30 дней или при подозрении на утечку)

### Stage 8+ (рекомендуется): через admin-endpoint

```bash
curl -sX POST https://api.example.com/admin/mtproto/rotate \
  -H "Authorization: Bearer $SUPERADMIN_JWT" \
  -H "content-type: application/json" \
  -d '{}'
# → {"secret_id": "...", "secret_hex": "ab12...", "cloak_domain": "www.microsoft.com",
#    "full_secret": "eeab12...", "config_line": "secret = \"eeab12...\"",
#    "host": "mtp.example.com", "port": 443,
#    "rotated_at": "2026-04-22T10:00:00Z", "revoked_secret_id": "..."}
```

API создаёт новый `MtprotoSecret(scope='shared', ACTIVE)`, REVOKE'ит
старый, пишет `AuditLog(action='mtproto_rotated')` (без secret material).
Дальше:

1. Скопировать `config_line` из ответа в `mtg/config.toml` (заменить
   текущую строку `secret = "..."`).
2. `docker compose restart mtg` на mtg-VPS.
3. **Бот автоматически разошлёт новый deep-link всем активным
   юзерам** (см. админ-панель TZ §9A.7) — отложено до Stage 9+.

> Для **dev** API сидит секрет автоматически из
> `API_MTG_SHARED_SECRET_HEX` при старте (см. `api/README.md` →
> Settings). В prod аналогично — секрет в env, ротация — через
> admin-endpoint.

### Manual fallback (без API)

1. Сгенерировать новый секрет (см. выше).
2. Заменить `secret = "..."` в `config.toml`.
3. `docker compose restart mtg`.
4. Вручную обновить `MtprotoSecret` в БД (status='REVOKED' для
   старого + INSERT нового ACTIVE).

## Метрики (Prometheus)

Доступны только на `127.0.0.1:9410/metrics`. Подключаются к Prometheus
control-plane через WireGuard (см. TZ §10.2).

## Безопасность

- **nftables**: разрешает только `:8443/tcp` снаружи + Prometheus только с `127.0.0.1`.
- **Anti-replay** включён (см. config).
- **Block-list** обновляется каждые 6 часов из публичных списков сканеров.
- **Логи без PII** (только агрегированная статистика).

## ⚠️ Важно
В **production** mtg развёрнут на **отдельном VPS** с отдельным IP (`mtp.example.com`),
чтобы блокировка IP MTProto-прокси не задевала основную VPN-ноду
(`fi-01.example.com`). См. TZ §9A.8.

## Per-user pool (Stage 9)

Per-user MTProto использует **pre-seeded FREE-pool** в БД +
`mtg_per_user_pool_items` в Ansible. Один контейнер mtg на каждый
порт пула. Подробности — `docs/ARCHITECTURE.md` §20.

### Bootstrap workflow (operator)

```bash
# 1. Bootstrap пула в БД (idempotent). Получаешь secret material
#    ОДИН РАЗ. Сохрани response — больше его не достать иначе как
#    через GET /admin/mtproto/pool/config.
curl -sX POST https://api.example.com/admin/mtproto/pool/bootstrap \
  -H "Authorization: Bearer $SUPERADMIN_JWT" \
  -H "content-type: application/json" \
  -d '{"count": 16, "port_base": 8443, "cloak_domain": "www.microsoft.com"}' \
  | jq '.items | map({port, secret: .full_secret})' > pool_items.json
# → [{"port": 8443, "secret": "eeABCD...cloak_hex"}, ...]

# 2. Скармливаешь Ansible:
ansible-playbook -i inventory/hosts.yml site.yml --tags per_user \
  -e mtg_per_user_enabled=true \
  -e "@pool_items.json"

# 3. Включаешь фичу в API:
echo "API_MTG_PER_USER_ENABLED=true" >> api/.env.dev
docker compose restart api

# 4. (опц.) Verify:
curl -s https://api.example.com/admin/mtproto/users \
  -H "Authorization: Bearer $JWT" | jq '.items[] | {port, status}'
```

### Регенерация config'ов после rotate/revoke

После `POST /admin/mtproto/users/{uid}/rotate` или /revoke порт
остаётся занят за REVOKED-строкой (mtg всё ещё держит секрет до
rebuild'а). Когда `pool_free_remaining` падает до критичного — bootstrap
ещё:

```bash
# 1. Bootstrap новых FREE-слотов поверх существующих (idempotent):
curl -sX POST .../pool/bootstrap -d '{"count": 32, "port_base": 8443}'
# inserted_ports содержит только новые порты, остальные skipped.

# 2. Полный dump source-of-truth для rebuild mtg config:
curl -s .../pool/config -H "Authorization: Bearer $JWT" \
  | jq '.items | map({port, secret: .full_secret})' > pool_items.json
ansible-playbook ... --tags per_user -e "@pool_items.json"
```

### Local e2e (docker-compose)

`docker-compose.dev.yml` содержит профиль `per-user-mtg` с 4
сервисами `mtg-8444..mtg-8447`. Перед запуском:

```bash
# 1. Bootstrap (через локальный admin JWT):
curl -sX POST http://localhost:8000/admin/mtproto/pool/bootstrap ... \
  -d '{"count": 4, "port_base": 8444}' > bootstrap.json

# 2. Render configs:
mkdir -p mtg/pool
jq -r '.items[] | "\(.port)\t\(.full_secret)"' bootstrap.json \
  | while IFS=$'\t' read port secret; do
    sed -e "s/{{ secret }}/$secret/" -e "s/{{ port }}/$port/" \
      -e "s/{{ port + 1000 }}/$((port + 1000))/" \
      mtg/config.template.toml > mtg/pool/$port.toml
  done

# 3. Up:
API_MTG_PER_USER_ENABLED=true docker compose --profile per-user-mtg up
```
