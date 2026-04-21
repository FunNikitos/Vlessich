# =============================================================================
# Vlessich — Cloudflare infrastructure (Terraform)
# =============================================================================
# Управляет: DNS-записи, Zero Trust Access для admin-панели, WAF-правила,
# Pages-проекты (webapp + admin), Workers (subscription + DoH), Email Routing.
#
# Использование:
#   terraform init
#   terraform plan  -var-file=terraform.tfvars
#   terraform apply -var-file=terraform.tfvars
#
# Секреты (API token, account_id, zone_id) — через sops + age, НЕ в репо.
# =============================================================================

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.40"
    }
  }

  # Рекомендуется удалённый state (R2 / S3-совместимое):
  # backend "s3" {
  #   bucket                      = "vlessich-tfstate"
  #   key                         = "cloudflare/terraform.tfstate"
  #   endpoint                    = "https://<account>.r2.cloudflarestorage.com"
  #   region                      = "auto"
  #   skip_credentials_validation = true
  #   skip_region_validation      = true
  # }
}

# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------

variable "cloudflare_api_token" {
  description = "Cloudflare API Token с правами Zone:Edit + Account:Edit + Pages/Workers/Access"
  type        = string
  sensitive   = true
}

variable "cf_account_id" {
  description = "Cloudflare Account ID"
  type        = string
}

variable "cf_zone_id" {
  description = "Cloudflare Zone ID для example.com"
  type        = string
}

variable "domain" {
  description = "Основной домен проекта"
  type        = string
  default     = "example.com"
}

variable "fi01_ip" {
  description = "Публичный IPv4 основной FI-ноды (VPN-инбаунд)"
  type        = string
}

variable "fi02_ip" {
  description = "Публичный IPv4 резервной FI-ноды"
  type        = string
  default     = ""
}

variable "mtp_ip" {
  description = "Публичный IPv4 MTProto-прокси (отдельный VPS — см. TZ §9A)"
  type        = string
}

variable "control_plane_ip" {
  description = "IP control-plane сервера (API / panel) — за Cloudflare proxied"
  type        = string
}

variable "admin_allowed_emails" {
  description = "Email'ы с доступом к admin-панели через Cloudflare Access"
  type        = list(string)
}

variable "admin_ip_allowlist" {
  description = "IP/CIDR для whitelist админки (доп. к email-auth)"
  type        = list(string)
  default     = []
}

variable "forward_email_to" {
  description = "Личный email для forwarding с admin@/support@/abuse@"
  type        = string
}

variable "backend_secret" {
  description = "HMAC-SHA256 ключ для подписи запросов sub-Worker → backend (см. TZ §11A)"
  type        = string
  sensitive   = true
}

variable "ip_salt" {
  description = "Соль для sha256(ip + salt) в логах Worker'ов (без PII)"
  type        = string
  sensitive   = true
}

# -----------------------------------------------------------------------------
# Provider
# -----------------------------------------------------------------------------

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# -----------------------------------------------------------------------------
# Zone-level settings (SSL, security, performance)
# -----------------------------------------------------------------------------

resource "cloudflare_zone_settings_override" "main" {
  zone_id = var.cf_zone_id

  settings {
    ssl                      = "strict"  # Full (strict)
    always_use_https         = "on"
    automatic_https_rewrites = "on"
    min_tls_version          = "1.2"
    tls_1_3                  = "on"
    opportunistic_encryption = "on"
    http3                    = "on"
    zero_rtt                 = "on"
    brotli                   = "on"
    ipv6                     = "on"
    websockets               = "on"
    # Security
    security_level           = "medium"
    browser_check            = "on"
    challenge_ttl            = 1800
    # Caching defaults
    browser_cache_ttl        = 14400

    security_header {
      enabled            = true
      preload            = true
      max_age            = 31536000
      include_subdomains = true
      nosniff            = true
    }
  }
}

# -----------------------------------------------------------------------------
# DNSSEC
# -----------------------------------------------------------------------------

resource "cloudflare_zone_dnssec" "main" {
  zone_id = var.cf_zone_id
}

# -----------------------------------------------------------------------------
# DNS records
# -----------------------------------------------------------------------------

# Control-plane (proxied — Cloudflare защищает)
resource "cloudflare_record" "apex" {
  zone_id = var.cf_zone_id
  name    = "@"
  type    = "A"
  value   = var.control_plane_ip
  proxied = true
  ttl     = 1
  comment = "Apex — лендинг-фасад (Finnish Cloud Services)"
}

resource "cloudflare_record" "www" {
  zone_id = var.cf_zone_id
  name    = "www"
  type    = "CNAME"
  value   = var.domain
  proxied = true
  ttl     = 1
}

resource "cloudflare_record" "api" {
  zone_id = var.cf_zone_id
  name    = "api"
  type    = "A"
  value   = var.control_plane_ip
  proxied = true
  ttl     = 1
  comment = "Backend FastAPI"
}

resource "cloudflare_record" "sub" {
  zone_id = var.cf_zone_id
  name    = "sub"
  type    = "A"
  value   = var.control_plane_ip
  proxied = true
  ttl     = 1
  comment = "Subscription URL (через Worker)"
}

resource "cloudflare_record" "status" {
  zone_id = var.cf_zone_id
  name    = "status"
  type    = "A"
  value   = var.control_plane_ip
  proxied = true
  ttl     = 1
  comment = "Uptime-Kuma"
}

# Pages (app / admin) — CNAME на Pages-проекты создаются автоматически,
# но можно зафиксировать вручную
resource "cloudflare_record" "app" {
  zone_id = var.cf_zone_id
  name    = "app"
  type    = "CNAME"
  value   = cloudflare_pages_project.webapp.subdomain
  proxied = true
  ttl     = 1
  comment = "Telegram Mini-App"
}

resource "cloudflare_record" "admin" {
  zone_id = var.cf_zone_id
  name    = "admin"
  type    = "CNAME"
  value   = cloudflare_pages_project.admin.subdomain
  proxied = true
  ttl     = 1
  comment = "Admin panel (защищён Access)"
}

# DoH endpoint (Worker)
resource "cloudflare_record" "dns" {
  zone_id = var.cf_zone_id
  name    = "dns"
  type    = "A"
  value   = "192.0.2.1" # dummy, Worker overrides via route
  proxied = true
  ttl     = 1
  comment = "DoH endpoint (Worker)"
}

# VPN-ноды (NON-proxied — Cloudflare не пропускает не-HTTP трафик)
resource "cloudflare_record" "fi01" {
  zone_id = var.cf_zone_id
  name    = "fi-01"
  type    = "A"
  value   = var.fi01_ip
  proxied = false
  ttl     = 300
  comment = "FI-нода #1 (VPN inbound) — non-proxied"
}

resource "cloudflare_record" "fi02" {
  count   = var.fi02_ip != "" ? 1 : 0
  zone_id = var.cf_zone_id
  name    = "fi-02"
  type    = "A"
  value   = var.fi02_ip
  proxied = false
  ttl     = 300
  comment = "FI-нода #2 (резерв) — non-proxied"
}

resource "cloudflare_record" "mtp" {
  zone_id = var.cf_zone_id
  name    = "mtp"
  type    = "A"
  value   = var.mtp_ip
  proxied = false
  ttl     = 300
  comment = "MTProto-прокси (отдельный IP) — non-proxied"
}

# CAA — запрет всем CA кроме Let's Encrypt
resource "cloudflare_record" "caa_issue" {
  zone_id = var.cf_zone_id
  name    = "@"
  type    = "CAA"
  data {
    flags = "0"
    tag   = "issue"
    value = "letsencrypt.org"
  }
}

resource "cloudflare_record" "caa_issuewild" {
  zone_id = var.cf_zone_id
  name    = "@"
  type    = "CAA"
  data {
    flags = "0"
    tag   = "issuewild"
    value = ";"
  }
}

# SPF — не шлём почту, жёсткий deny
resource "cloudflare_record" "spf" {
  zone_id = var.cf_zone_id
  name    = "@"
  type    = "TXT"
  value   = "v=spf1 -all"
  ttl     = 3600
}

# DMARC — reject + отчёты на abuse@
resource "cloudflare_record" "dmarc" {
  zone_id = var.cf_zone_id
  name    = "_dmarc"
  type    = "TXT"
  value   = "v=DMARC1; p=reject; sp=reject; rua=mailto:abuse@${var.domain}; ruf=mailto:abuse@${var.domain}; fo=1; adkim=s; aspf=s"
  ttl     = 3600
}

# -----------------------------------------------------------------------------
# Email Routing — forward admin@/support@/abuse@ на личную почту
# -----------------------------------------------------------------------------

resource "cloudflare_email_routing_settings" "main" {
  zone_id = var.cf_zone_id
  enabled = true
}

resource "cloudflare_email_routing_address" "personal" {
  account_id = var.cf_account_id
  email      = var.forward_email_to
}

locals {
  aliases = ["admin", "support", "abuse", "hello", "noc"]
}

resource "cloudflare_email_routing_rule" "forward" {
  for_each = toset(local.aliases)

  zone_id = var.cf_zone_id
  name    = "Forward ${each.key}"
  enabled = true

  matcher {
    type  = "literal"
    field = "to"
    value = "${each.key}@${var.domain}"
  }

  action {
    type  = "forward"
    value = [var.forward_email_to]
  }

  depends_on = [cloudflare_email_routing_address.personal]
}

# -----------------------------------------------------------------------------
# Pages — Telegram Mini-App и Admin
# -----------------------------------------------------------------------------

resource "cloudflare_pages_project" "webapp" {
  account_id        = var.cf_account_id
  name              = "vlessich-webapp"
  production_branch = "main"

  build_config {
    build_command   = "npm ci && npm run build"
    destination_dir = "dist"
    root_dir        = "webapp"
  }

  deployment_configs {
    production {
      environment_variables = {
        VITE_API_URL = "https://api.${var.domain}"
        VITE_SUB_URL = "https://sub.${var.domain}"
      }
      compatibility_date = "2026-01-01"
    }
    preview {
      environment_variables = {
        VITE_API_URL = "https://api.${var.domain}"
      }
      compatibility_date = "2026-01-01"
    }
  }
}

resource "cloudflare_pages_project" "admin" {
  account_id        = var.cf_account_id
  name              = "vlessich-admin"
  production_branch = "main"

  build_config {
    build_command   = "npm ci && npm run build"
    destination_dir = "dist"
    root_dir        = "admin"
  }

  deployment_configs {
    production {
      environment_variables = {
        VITE_API_URL = "https://api.${var.domain}"
      }
      compatibility_date = "2026-01-01"
    }
  }
}

resource "cloudflare_pages_domain" "webapp" {
  account_id   = var.cf_account_id
  project_name = cloudflare_pages_project.webapp.name
  domain       = "app.${var.domain}"
}

resource "cloudflare_pages_domain" "admin" {
  account_id   = var.cf_account_id
  project_name = cloudflare_pages_project.admin.name
  domain       = "admin.${var.domain}"
}

# -----------------------------------------------------------------------------
# Zero Trust Access — защита admin.example.com
# -----------------------------------------------------------------------------

resource "cloudflare_zero_trust_access_application" "admin" {
  account_id                = var.cf_account_id
  name                      = "Vlessich Admin Panel"
  domain                    = "admin.${var.domain}"
  type                      = "self_hosted"
  session_duration          = "8h"
  auto_redirect_to_identity = false
  app_launcher_visible      = false
  http_only_cookie_attribute = true
  same_site_cookie_attribute = "strict"
}

resource "cloudflare_zero_trust_access_policy" "admin_allow" {
  application_id = cloudflare_zero_trust_access_application.admin.id
  account_id     = var.cf_account_id
  name           = "Allow admins"
  precedence     = 1
  decision       = "allow"

  include {
    email = var.admin_allowed_emails
  }

  # Доп. уровень: требуем попадание в IP-allowlist если он задан
  dynamic "require" {
    for_each = length(var.admin_ip_allowlist) > 0 ? [1] : []
    content {
      ip = var.admin_ip_allowlist
    }
  }
}

# -----------------------------------------------------------------------------
# WAF / Firewall Rules
# -----------------------------------------------------------------------------

# Rate-limit для /activate и /trial на API
resource "cloudflare_ruleset" "api_ratelimit" {
  zone_id     = var.cf_zone_id
  name        = "API Rate Limit"
  description = "Rate-limit критичных эндпоинтов"
  kind        = "zone"
  phase       = "http_ratelimit"

  rules {
    description = "Limit /activate to 10/min/IP"
    expression  = "(http.host eq \"api.${var.domain}\" and starts_with(http.request.uri.path, \"/activate\"))"
    action      = "block"
    ratelimit {
      characteristics     = ["cf.colo.id", "ip.src"]
      period              = 60
      requests_per_period = 10
      mitigation_timeout  = 600
    }
  }

  rules {
    description = "Limit /trial to 3/hour/IP"
    expression  = "(http.host eq \"api.${var.domain}\" and starts_with(http.request.uri.path, \"/trial\"))"
    action      = "block"
    ratelimit {
      characteristics     = ["cf.colo.id", "ip.src"]
      period              = 3600
      requests_per_period = 3
      mitigation_timeout  = 3600
    }
  }
}

# WAF — блок известных сканеров и ботов
resource "cloudflare_ruleset" "waf_custom" {
  zone_id     = var.cf_zone_id
  name        = "Custom WAF rules"
  description = "Блок сканеров + защита админки"
  kind        = "zone"
  phase       = "http_request_firewall_custom"

  rules {
    description = "Block scanner UAs"
    expression  = "(http.user_agent contains \"masscan\" or http.user_agent contains \"nmap\" or http.user_agent contains \"sqlmap\" or http.user_agent contains \"Censys\" or http.user_agent contains \"ZGrab\" or http.user_agent contains \"Shodan\")"
    action      = "block"
  }

  rules {
    description = "Challenge non-RU/EU to admin (extra layer)"
    expression  = "(http.host eq \"admin.${var.domain}\" and not ip.geoip.country in {\"RU\" \"FI\" \"DE\" \"NL\" \"EE\" \"LV\" \"LT\"})"
    action      = "managed_challenge"
  }

  rules {
    description = "Block bad bots globally"
    expression  = "(cf.client.bot and not cf.verified_bot_category in {\"Search Engine Crawler\" \"Search Engine Optimization\"})"
    action      = "block"
  }
}

# -----------------------------------------------------------------------------
# Workers — subscription и DoH
# -----------------------------------------------------------------------------

resource "cloudflare_workers_script" "subscription" {
  account_id = var.cf_account_id
  name       = "vlessich-subscription"
  content    = file("${path.module}/workers/subscription.js")

  # secret через wrangler + terraform
  secret_text_binding {
    name = "BACKEND_URL"
    text = "https://api.${var.domain}/internal/sub"
  }

  secret_text_binding {
    name = "BACKEND_SECRET"
    text = var.backend_secret
  }

  secret_text_binding {
    name = "IP_SALT"
    text = var.ip_salt
  }
}

resource "cloudflare_workers_route" "subscription" {
  zone_id     = var.cf_zone_id
  pattern     = "sub.${var.domain}/*"
  script_name = cloudflare_workers_script.subscription.name
}

resource "cloudflare_workers_script" "doh" {
  account_id = var.cf_account_id
  name       = "vlessich-doh"
  content    = file("${path.module}/workers/doh.js")

  plain_text_binding {
    name = "UPSTREAM_DOH"
    text = "https://cloudflare-dns.com/dns-query"
  }

  plain_text_binding {
    name = "FALLBACK_DOH"
    text = "https://dns.quad9.net/dns-query"
  }

  plain_text_binding {
    name = "ENABLE_ADBLOCK"
    text = "0"
  }

  secret_text_binding {
    name = "IP_SALT"
    text = var.ip_salt
  }
}

resource "cloudflare_workers_route" "doh" {
  zone_id     = var.cf_zone_id
  pattern     = "dns.${var.domain}/dns-query*"
  script_name = cloudflare_workers_script.doh.name
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "webapp_url"    { value = "https://app.${var.domain}" }
output "admin_url"     { value = "https://admin.${var.domain}" }
output "api_url"       { value = "https://api.${var.domain}" }
output "subscription_base" { value = "https://sub.${var.domain}" }
output "doh_endpoint"  { value = "https://dns.${var.domain}/dns-query" }
output "webapp_pages_subdomain" { value = cloudflare_pages_project.webapp.subdomain }
output "admin_pages_subdomain"  { value = cloudflare_pages_project.admin.subdomain }
