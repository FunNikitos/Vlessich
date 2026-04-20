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

1. Сгенерировать новый секрет (см. выше).
2. Заменить `secret = "..."` в `config.toml`.
3. `docker compose restart mtg`.
4. **Бот автоматически разошлёт новый deep-link всем активным юзерам** (см. админ-панель TZ §9A.7).

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
