# Vlessich — Caddy фасад для FI-ноды

## Что это
Caddy на FI-ноде выполняет три роли:
1. **Лендинг-фасад** «Finnish Cloud Services» (TZ §11.2) — нейтральная витрина,
   когда сканер/любопытный браузер ходят на IP ноды.
2. **Источник валидного TLS** для `fi-01.example.com` — авто Let's Encrypt.
3. **Reality fallback target** — Xray проксирует «неправильный» handshake
   на Caddy (loopback :8443), и сканер получает реальный сайт вместо ошибки.

## Деплой

```bash
# Через Ansible (см. ../ansible/roles/node/)
ansible-playbook -i inventory site.yml --tags caddy

# Или вручную:
docker run -d --name caddy --restart unless-stopped \
  --network host \
  -v $(pwd)/Caddyfile:/etc/caddy/Caddyfile:ro \
  -v caddy_data:/data \
  -v caddy_config:/config \
  -v /var/www/finnish-cloud-services:/var/www/finnish-cloud-services:ro \
  -v /var/log/caddy:/var/log/caddy \
  caddy:2-alpine
```

## Контент лендинга

Положить в `/var/www/finnish-cloud-services/`:
- `index.html` — главная (нейтральная: «cloud hosting», «IT consulting»).
- `about.html`, `services.html`, `contact.html`.
- `assets/` — CSS, картинки.
- `robots.txt` — разрешает индексацию для domain warming.
- `sitemap.xml` — для SEO (домен будет «тёплым» к релизу).

**Важно:** ни слова про VPN, обход блокировок, Роскомнадзор. Только
«облачные сервисы», «инфраструктура», «IT-консалтинг».

## Проверка

```bash
# TLS-grade (должен быть A+)
curl -I https://fi-01.example.com

# Security headers
curl -sI https://fi-01.example.com | grep -E "Strict|Content-Security|X-"

# HTTP/3
curl --http3 -I https://fi-01.example.com

# Healthcheck
curl https://fi-01.example.com/healthz
```

## Domain warming
Зарегистрируй сайт в Google Search Console (`fi-01.example.com`).
Через 2–4 недели Google начнёт его индексировать — IP/домен
получают статус «легитимный сайт» в глазах сканеров и DPI.
