# Vlessich — Ansible automation for FI-node

## Что делает
Один плейбук `site.yml` разворачивает FI-ноду «под ключ»:
- Базовые пакеты, NTP, unattended-upgrades.
- Sysctl tuning: BBR v3, увеличенные TCP/UDP buffers, file-limits.
- SSH hardening + custom port + fwknop SPA.
- Cowrie honeypot на :22.
- nftables: drop-policy + scanner-blocklist + RST для нестандартных портов.
- Docker Engine + Compose plugin.
- **Caddy** — HTTPS-фасад «Finnish Cloud Services», авто-LE серт.
- **Xray-core** — VLESS+Reality+XHTTP (H3 + H2) + Vision + Hysteria2 (см. TZ §10.3).
- **AdGuard Home** — DNS-фильтр на 127.0.0.1:53.
- **mtg** (опционально, по флагу) — MTProto-прокси.
- **Promtail + node_exporter** → Loki/Prometheus на control-plane.
- **Borg** — ежечасные бэкапы конфигов на S3.
- fail2ban с nftables-action.

## Подготовка

```bash
cd ansible/
cp inventory/hosts.example.yml inventory/hosts.yml
# Заполнить inventory: IP, hostname

# Создать vault для секретов
ansible-vault create group_vars/vpn_nodes/vault.yml
# → положить:
#   vault_fwknop_key_base64: "..."
#   vault_fwknop_hmac_base64: "..."
#   vault_borg_passphrase: "..."

# Положить SSH-ключи администраторов в group_vars/all.yml
# → ssh_pubkeys: ["ssh-ed25519 AAAA... admin@laptop"]
```

## Деплой

```bash
# Полный provisioning
ansible-playbook -i inventory/hosts.yml site.yml --ask-vault-pass

# Только обновить Xray-конфиг
ansible-playbook -i inventory/hosts.yml site.yml --tags xray

# Только nftables
ansible-playbook -i inventory/hosts.yml site.yml --tags nftables

# Включить mtg на этой ноде
ansible-playbook -i inventory/hosts.yml site.yml --tags mtg \
  -e mtg_enabled=true
```

## Через Makefile (рекомендуется)

```bash
make deploy-node HOST=fi-01
make rotate-mtg-secret HOST=mtp
make refresh-blocklists HOST=fi-01
```

## Проверка после деплоя

```bash
ansible vpn_nodes -i inventory/hosts.yml -m shell -a "docker ps"
ansible vpn_nodes -i inventory/hosts.yml -m shell -a "nft list ruleset"
ansible vpn_nodes -i inventory/hosts.yml -m shell -a "ss -tulpn | grep -E '443|8443|8444'"
curl -I https://fi-01.example.com    # должен быть валидный TLS + HSTS
```

## Структура

```
ansible/
├── site.yml                       # entrypoint
├── inventory/
│   └── hosts.example.yml
├── group_vars/
│   ├── all.yml                    # общие переменные (ssh_pubkeys и т.п.)
│   └── vpn_nodes/
│       └── vault.yml              # секреты (ansible-vault encrypted)
└── roles/
    └── node/
        ├── defaults/main.yml      # все переменные с дефолтами
        ├── handlers/main.yml      # restart-handlers
        ├── tasks/
        │   ├── main.yml           # entrypoint
        │   ├── sysctl.yml
        │   ├── ssh.yml
        │   ├── nftables.yml
        │   ├── fwknop.yml
        │   ├── cowrie.yml
        │   ├── docker.yml
        │   ├── caddy.yml
        │   ├── xray.yml
        │   ├── adguardhome.yml
        │   ├── mtg.yml
        │   ├── monitoring.yml
        │   ├── backup.yml
        │   └── fail2ban.yml
        └── templates/
            ├── nftables.conf.j2
            ├── Caddyfile.j2
            ├── xray.config.json.j2
            ├── AdGuardHome.yaml.j2
            └── mtg.config.toml.j2
```
