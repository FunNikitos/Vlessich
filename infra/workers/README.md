# Vlessich — Cloudflare Workers

Два Worker'а на edge:

| Worker          | Route                          | Назначение                                          |
|-----------------|--------------------------------|-----------------------------------------------------|
| `subscription`  | `sub.<domain>/*`               | Edge-выдача subscription URL (V2Ray / Clash / sing-box / Surge) |
| `doh`           | `dns.<domain>/dns-query*`      | DNS-over-HTTPS, RFC 8484 + application/dns-json     |

## Деплой через Terraform

Оба скрипта подхватываются `cloudflare.tf` через `file("${path.module}/workers/*.js")`.
Bindings (секреты и переменные) прописаны там же; значения секретов берутся из
`terraform.tfvars.enc` (sops).

```bash
cd infra
sops --decrypt terraform.tfvars.enc > terraform.tfvars
terraform apply
shred -u terraform.tfvars
```

## Локальный dev через wrangler (опционально)

Используется только для локальной отладки (`wrangler dev`). В проде Terraform
остаётся единственным источником правды.

```bash
npm i -g wrangler
wrangler dev infra/workers/subscription.js --local
wrangler dev infra/workers/doh.js --local
```

## Контракты и bindings

### `subscription` Worker
Переменные окружения / секреты:
- `BACKEND_URL` — `https://api.<domain>/internal/sub` (plain).
- `BACKEND_SECRET` — HMAC-SHA256 ключ (secret).
- `IP_SALT` — 32+ байт соли для хэширования IP в логах (secret).

Контракт к backend'у см. в `subscription.js` (верх файла) + `TZ.md §11A.3`.

### `doh` Worker
Переменные:
- `UPSTREAM_DOH` — upstream DoH endpoint (default: `https://cloudflare-dns.com/dns-query`).
- `FALLBACK_DOH` — резервный upstream (default: `https://dns.quad9.net/dns-query`).
- `ENABLE_ADBLOCK` — `"1"` для активации фильтрации через KV (default: `"0"`).
- `IP_SALT` — соль для будущего rate-limiting (secret).
- `BLOCKLIST_KV` *(optional KV binding)* — ключ = lowercased FQDN, value = `"1"`.

Если нужен adblock, добавить KV namespace:

```hcl
# cloudflare.tf (опционально)
resource "cloudflare_workers_kv_namespace" "blocklist" {
  account_id = var.cf_account_id
  title      = "vlessich-blocklist"
}

# внутри cloudflare_workers_script.doh
kv_namespace_binding {
  name         = "BLOCKLIST_KV"
  namespace_id = cloudflare_workers_kv_namespace.blocklist.id
}
```

## Non-negotiables

- Zero PII: никакого логирования query name, полного IP, токенов.
- Только `sha256(ip + IP_SALT)` попадает в метрики/трейсы.
- Reject payloads >4 KiB (DoH) / >128 hex chars token (sub).
- `content-type: application/dns-message` строго обязателен для POST к DoH.
