# Vlessich — Cloudflare infrastructure (Terraform)

## Что внутри
- **DNS** для всех поддоменов (см. TZ §11A.1).
- **Zero Trust Access** для `admin.example.com` (заменяет TOTP в MVP).
- **WAF custom rules** + rate-limit для `/activate`, `/trial`.
- **Pages** проекты: `webapp` (Mini-App) и `admin`.
- **Workers**: `subscription` (edge-выдача подписки) + `doh` (DoH endpoint).
- **Email Routing** для `admin@`, `support@`, `abuse@`.
- **DNSSEC**, **CAA**, **SPF/DMARC**.

## Подготовка

1. Установить Terraform ≥1.7 и Cloudflare CLI (`wrangler`).
2. Создать API-токен: `Account → API Tokens → Create Token`.
   Минимальные права:
   - `Zone:DNS:Edit`, `Zone:Zone Settings:Edit`, `Zone:DNSSEC:Edit`,
   - `Account:Email Routing Addresses:Edit`,
   - `Account:Cloudflare Pages:Edit`,
   - `Account:Workers Scripts:Edit`,
   - `Account:Access: Apps and Policies:Edit`.
3. Зашифровать `terraform.tfvars` через `sops` (см. ниже).

## terraform.tfvars (через sops)

```hcl
cloudflare_api_token  = "cf_xxx"
cf_account_id         = "abc123"
cf_zone_id            = "def456"
domain                = "example.com"
fi01_ip               = "1.2.3.4"
fi02_ip               = "1.2.3.5"
mtp_ip                = "5.6.7.8"
control_plane_ip      = "9.9.9.9"
admin_allowed_emails  = ["you@gmail.com"]
admin_ip_allowlist    = ["203.0.113.10/32"]   # опционально
forward_email_to      = "you@gmail.com"
backend_secret        = "<openssl rand -hex 32>"
ip_salt               = "<openssl rand -hex 32>"
```

Зашифровать:
```bash
sops --encrypt --age <PUBLIC_AGE_KEY> terraform.tfvars > terraform.tfvars.enc
```

## Workflow

```bash
terraform init
sops --decrypt terraform.tfvars.enc > terraform.tfvars
terraform plan
terraform apply
shred -u terraform.tfvars
```

## Workers
В `workers/subscription.js` и `workers/doh.js` — production-код Worker'ов.
Полная документация и контракт: `workers/README.md`.

## Backup state
Раскомментируй блок `backend "s3"` в `cloudflare.tf` после создания R2-бакета
`vlessich-tfstate` (или используй Terraform Cloud).
