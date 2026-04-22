#!/usr/bin/env bash
# Vlessich one-liner installer (Stage 13).
# Target: clean Ubuntu 22.04 / 24.04, single-host all-in-one topology.
#
# Usage (one-liner):
#   curl -fsSL https://raw.githubusercontent.com/FunNikitos/Vlessich/master/scripts/install.sh \
#     | sudo BOT_TOKEN=123:abc bash
#
# Usage (local clone):
#   sudo bash scripts/install.sh
#
# Env overrides (skip prompts when set):
#   BOT_TOKEN          Telegram bot token (required)
#   PUBLIC_DOMAIN      api/admin/webapp public hostname (optional → polling mode)
#   ADMIN_EMAIL        admin login email          (default admin@localhost)
#   VLESSICH_DIR       install dir                (default /opt/vlessich)
#   VLESSICH_REPO      git repo to clone          (default https://github.com/FunNikitos/Vlessich.git)
#   VLESSICH_BRANCH    branch to track            (default master)
#   VLESSICH_PROFILES  comma-separated compose profiles (e.g. "mtproto,ruleset")
#   VLESSICH_FORCE_OS  set =1 to bypass OS check
#
# Idempotent: re-runs reuse existing .secrets/, pull latest code, re-up
# compose. Existing admin user is not overwritten.
#
# Exit codes:
#   0 success
#   1 generic failure
#   2 OS / arch check failed (override with VLESSICH_FORCE_OS=1)
#   3 BOT_TOKEN missing or malformed
#   4 docker install failed

set -Eeuo pipefail

# ---------- constants & helpers ----------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
LIB_DIR="${SCRIPT_DIR}/lib"

VLESSICH_DIR="${VLESSICH_DIR:-/opt/vlessich}"
VLESSICH_REPO="${VLESSICH_REPO:-https://github.com/FunNikitos/Vlessich.git}"
VLESSICH_BRANCH="${VLESSICH_BRANCH:-master}"
VLESSICH_PROFILES="${VLESSICH_PROFILES:-}"

readonly C_RESET='\033[0m'
readonly C_BOLD='\033[1m'
readonly C_GREEN='\033[32m'
readonly C_YELLOW='\033[33m'
readonly C_RED='\033[31m'
readonly C_BLUE='\033[34m'

log()   { printf '%b[vlessich]%b %s\n' "${C_BLUE}" "${C_RESET}" "$*"; }
ok()    { printf '%b[ ok ]%b %s\n'    "${C_GREEN}" "${C_RESET}" "$*"; }
warn()  { printf '%b[warn]%b %s\n'    "${C_YELLOW}" "${C_RESET}" "$*" >&2; }
err()   { printf '%b[err ]%b %s\n'    "${C_RED}" "${C_RESET}" "$*" >&2; }
die()   { err "$*"; exit "${2:-1}"; }

trap 'err "installer aborted at line $LINENO"; exit 1' ERR

# ---------- 1. preflight ----------
preflight() {
  log "preflight: checking host"
  if [[ "${EUID}" -ne 0 ]]; then
    die "must run as root (use sudo)" 1
  fi

  local arch
  arch="$(uname -m)"
  case "${arch}" in
    x86_64|aarch64) ok "arch ${arch}" ;;
    *) die "unsupported arch ${arch} (need x86_64 or aarch64)" 2 ;;
  esac

  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "${ID:-}" != "ubuntu" ]]; then
      if [[ "${VLESSICH_FORCE_OS:-0}" != "1" ]]; then
        die "this installer supports Ubuntu only (got ID=${ID:-unknown}); set VLESSICH_FORCE_OS=1 to bypass" 2
      fi
      warn "non-Ubuntu OS (${ID:-?}) — proceeding under VLESSICH_FORCE_OS=1"
    fi
    case "${VERSION_ID:-}" in
      22.04|24.04) ok "Ubuntu ${VERSION_ID}" ;;
      *)
        if [[ "${VLESSICH_FORCE_OS:-0}" != "1" ]]; then
          die "tested only on Ubuntu 22.04 / 24.04 (got ${VERSION_ID:-unknown}); set VLESSICH_FORCE_OS=1 to bypass" 2
        fi
        warn "untested Ubuntu ${VERSION_ID:-?} — proceeding under VLESSICH_FORCE_OS=1"
        ;;
    esac
  else
    warn "/etc/os-release missing, skipping OS detection"
  fi

  for port in 8000 5173 5174 5432 6379; do
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}\$"; then
      warn "port ${port} already in use — compose will fail to bind"
    fi
  done
}

# ---------- 2. apt deps ----------
install_apt_deps() {
  log "installing apt prerequisites"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    ca-certificates curl gnupg openssl git lsb-release \
    apt-transport-https iproute2 jq >/dev/null
  ok "apt deps installed"
}

# ---------- 3. docker ----------
install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "docker $(docker --version | awk '{print $3}' | tr -d ',') already installed"
    return 0
  fi

  log "installing Docker via official get.docker.com script"
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh >/dev/null 2>&1 || die "docker install failed" 4
  rm -f /tmp/get-docker.sh

  if ! docker compose version >/dev/null 2>&1; then
    die "docker compose v2 plugin missing after install" 4
  fi

  systemctl enable --now docker >/dev/null 2>&1 || warn "could not enable docker service"

  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    usermod -aG docker "${SUDO_USER}" || warn "could not add ${SUDO_USER} to docker group"
    log "added ${SUDO_USER} to docker group (re-login required to use docker without sudo)"
  fi
  ok "docker installed"
}

# ---------- 4. repo ----------
clone_or_update_repo() {
  if [[ -d "${VLESSICH_DIR}/.git" ]]; then
    log "repo exists at ${VLESSICH_DIR}, updating"
    git -C "${VLESSICH_DIR}" fetch --quiet origin "${VLESSICH_BRANCH}" || warn "git fetch failed"
    git -C "${VLESSICH_DIR}" checkout --quiet "${VLESSICH_BRANCH}" || warn "git checkout failed"
    if ! git -C "${VLESSICH_DIR}" pull --ff-only --quiet origin "${VLESSICH_BRANCH}" 2>/dev/null; then
      warn "git pull --ff-only failed (diverged?), keeping current HEAD"
    fi
  elif [[ -f "${VLESSICH_DIR}/docker-compose.prod.yml" ]]; then
    ok "repo present at ${VLESSICH_DIR} (non-git, skipping clone)"
  else
    log "cloning ${VLESSICH_REPO} → ${VLESSICH_DIR}"
    git clone --quiet --branch "${VLESSICH_BRANCH}" "${VLESSICH_REPO}" "${VLESSICH_DIR}"
  fi
  ok "repo ready at ${VLESSICH_DIR}"
}

# ---------- 5. secrets ----------
gen_hex32() { openssl rand -hex 32; }
gen_password() { openssl rand -base64 24 | tr -d '/+=' | head -c 24; }

ensure_secret_file() {
  local path="$1" content="$2"
  if [[ -f "${path}" ]]; then
    return 0
  fi
  printf '%s' "${content}" > "${path}"
  chmod 600 "${path}"
}

write_secrets() {
  local sdir="${VLESSICH_DIR}/.secrets"
  mkdir -p "${sdir}"
  chmod 700 "${sdir}"

  ensure_secret_file "${sdir}/api_internal_secret"  "$(gen_hex32)"
  ensure_secret_file "${sdir}/api_secretbox_key"    "$(gen_hex32)"
  ensure_secret_file "${sdir}/api_jwt_secret"       "$(gen_hex32)"
  ensure_secret_file "${sdir}/pg_password"          "$(gen_hex32)"
  ensure_secret_file "${sdir}/admin_password"       "$(gen_password)"

  ok "secrets in ${sdir} (chmod 600)"
}

read_secret() { cat "${VLESSICH_DIR}/.secrets/$1"; }

# ---------- 6. interactive prompts ----------
prompt_inputs() {
  if [[ -z "${BOT_TOKEN:-}" ]]; then
    if [[ -t 0 ]]; then
      printf 'Enter Telegram BOT_TOKEN (from @BotFather): '
      read -r BOT_TOKEN
    fi
  fi
  if [[ -z "${BOT_TOKEN:-}" ]]; then
    die "BOT_TOKEN is required (export BOT_TOKEN=... or pass via stdin)" 3
  fi
  if ! [[ "${BOT_TOKEN}" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]]; then
    die "BOT_TOKEN format invalid (expected '<digits>:<token>')" 3
  fi

  if [[ -z "${PUBLIC_DOMAIN:-}" && -t 0 ]]; then
    printf 'Public domain for api/admin/webapp (leave empty to use polling, no public TLS): '
    read -r PUBLIC_DOMAIN
  fi
  PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-}"

  if [[ -z "${ADMIN_EMAIL:-}" && -t 0 ]]; then
    printf 'Admin email [admin@localhost]: '
    read -r ADMIN_EMAIL
  fi
  ADMIN_EMAIL="${ADMIN_EMAIL:-admin@localhost}"
}

# ---------- 7. render env files ----------
render_env_files() {
  local sdir="${VLESSICH_DIR}/.secrets"
  local internal_secret secretbox jwt pg_pw

  internal_secret="$(read_secret api_internal_secret)"
  secretbox="$(read_secret api_secretbox_key)"
  jwt="$(read_secret api_jwt_secret)"
  pg_pw="$(read_secret pg_password)"

  local public_base="http://localhost:8000"
  if [[ -n "${PUBLIC_DOMAIN}" ]]; then
    public_base="https://${PUBLIC_DOMAIN}"
  fi

  cat > "${sdir}/db.env" <<EOF
POSTGRES_DB=vlessich
POSTGRES_USER=vlessich
POSTGRES_PASSWORD=${pg_pw}
EOF
  chmod 600 "${sdir}/db.env"

  cat > "${sdir}/api.env" <<EOF
API_ENV=prod
API_LOG_LEVEL=INFO
API_DATABASE_URL=postgresql+asyncpg://vlessich:${pg_pw}@db:5432/vlessich
API_REDIS_URL=redis://redis:6379/1
API_INTERNAL_SECRET=${internal_secret}
API_SECRETBOX_KEY=${secretbox}
API_PUBLIC_BASE_URL=${public_base}
API_CORS_ORIGINS=["${public_base}","http://localhost:5173","http://localhost:5174"]
API_REMNAWAVE_MODE=mock
API_ADMIN_JWT_SECRET=${jwt}
API_ADMIN_JWT_TTL_SEC=3600
API_ADMIN_BCRYPT_COST=12
API_PROBE_INTERVAL_SEC=60
API_PROBE_TIMEOUT_SEC=5
API_PROBE_PORT=443
API_PROBE_BURN_THRESHOLD=3
API_PROBE_RECOVER_THRESHOLD=5
API_PROBE_METRICS_PORT=9101
API_RU_PROBE_TIMEOUT_SEC=8
API_MTG_SHARED_CLOAK=www.microsoft.com
API_MTG_PER_USER_ENABLED=false
API_MTG_PER_USER_POOL_SIZE=16
API_MTG_PER_USER_PORT_BASE=8443
API_MTG_AUTO_ROTATION_ENABLED=false
API_MTG_SHARED_ROTATION_DAYS=30
API_MTG_ROTATOR_INTERVAL_SEC=3600
API_MTG_BROADCAST_ENABLED=false
API_MTG_BROADCAST_COOLDOWN_SEC=3600
API_MTG_BROADCAST_IDEMPOTENCY_TTL_SEC=86400
API_MTG_BROADCAST_RL_GLOBAL_PER_SEC=30
API_MTG_BROADCAST_RL_PER_CHAT_SEC=1
API_MTG_BROADCAST_STREAM_MAXLEN=10000
API_MTG_BROADCAST_BOT_NOTIFY_URL=http://bot:8081/internal/notify/mtproto_rotated
API_BILLING_ENABLED=false
API_BILLING_PLAN_TTL_PENDING_SEC=3600
API_BILLING_REFUND_BOT_NOTIFY_URL=http://bot:8081/internal/refund/star_payment
API_SMART_ROUTING_ENABLED=false
API_RULESET_PULLER_ENABLED=false
API_RULESET_PULL_INTERVAL_SEC=21600
API_RULESET_PULLER_METRICS_PORT=9104
API_RULESET_HTTP_TIMEOUT_SEC=30
API_RULESET_STALE_AFTER_SEC=86400
EOF
  chmod 600 "${sdir}/api.env"

  local webhook_block=""
  if [[ -n "${PUBLIC_DOMAIN}" ]]; then
    local webhook_secret
    webhook_secret="$(gen_hex32)"
    webhook_block="BOT_WEBHOOK_URL=https://${PUBLIC_DOMAIN}/telegram/webhook
BOT_WEBHOOK_SECRET=${webhook_secret}"
  fi

  cat > "${sdir}/bot.env" <<EOF
BOT_ENV=prod
BOT_LOG_LEVEL=INFO
BOT_TOKEN=${BOT_TOKEN}
BOT_API_BASE_URL=http://api:8000
BOT_API_INTERNAL_SECRET=${internal_secret}
BOT_REDIS_URL=redis://redis:6379/0
BOT_WEBAPP_URL=${public_base}
BOT_SUPPORT_USERNAME=vlessich_support
BOT_INTERNAL_NOTIFY_ENABLED=true
BOT_INTERNAL_NOTIFY_HOST=0.0.0.0
BOT_INTERNAL_NOTIFY_PORT=8081
BOT_INTERNAL_NOTIFY_PATH=/internal/notify/mtproto_rotated
BOT_BILLING_ENABLED=false
BOT_INTERNAL_REFUND_PATH=/internal/refund/star_payment
BOT_SMART_ROUTING_ENABLED=false
${webhook_block}
EOF
  chmod 600 "${sdir}/bot.env"

  ok "rendered .secrets/{db,api,bot}.env"
}

# ---------- 8. compose up ----------
compose_up() {
  log "docker compose build & up (this may take a few minutes)"
  local profile_args=()
  if [[ -n "${VLESSICH_PROFILES}" ]]; then
    IFS=',' read -ra _profs <<< "${VLESSICH_PROFILES}"
    for p in "${_profs[@]}"; do
      profile_args+=(--profile "${p}")
    done
    log "compose profiles enabled: ${VLESSICH_PROFILES}"
  fi

  (
    cd "${VLESSICH_DIR}"
    docker compose -f docker-compose.prod.yml "${profile_args[@]}" pull --quiet || warn "docker pull warned"
    docker compose -f docker-compose.prod.yml "${profile_args[@]}" up -d --build
  )

  log "waiting for api /healthz (timeout 180s)"
  local i=0
  while ! curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; do
    i=$((i + 3))
    if [[ ${i} -gt 180 ]]; then
      warn "api did not become healthy in 180s — check 'docker compose logs api'"
      return 0
    fi
    sleep 3
  done
  ok "api is healthy"
}

# ---------- 9. admin bootstrap ----------
bootstrap_admin() {
  local admin_pw
  admin_pw="$(read_secret admin_password)"

  log "ensuring superadmin ${ADMIN_EMAIL} exists"
  (
    cd "${VLESSICH_DIR}"
    docker compose -f docker-compose.prod.yml exec -T api \
      python -m app.scripts.create_admin \
        --email "${ADMIN_EMAIL}" \
        --password "${admin_pw}" \
        --role superadmin \
      || warn "create_admin returned non-zero (already exists is OK)"
  )
}

# ---------- 10. final report ----------
final_report() {
  local admin_pw bot_username
  admin_pw="$(read_secret admin_password)"
  bot_username="$(curl -fsS "https://api.telegram.org/bot${BOT_TOKEN}/getMe" 2>/dev/null \
    | jq -r '.result.username // "unknown"' 2>/dev/null || echo "unknown")"

  printf '\n'
  printf '%b════════════════════════════════════════════════════════════════%b\n' "${C_GREEN}" "${C_RESET}"
  printf '%b  Vlessich is up                                                  %b\n' "${C_BOLD}" "${C_RESET}"
  printf '%b════════════════════════════════════════════════════════════════%b\n' "${C_GREEN}" "${C_RESET}"
  printf '\n'
  printf '  install dir : %s\n' "${VLESSICH_DIR}"
  printf '  bot         : @%s (token in .secrets/bot.env)\n' "${bot_username}"
  printf '  api         : http://127.0.0.1:8000 (healthz: /healthz)\n'
  printf '  webapp      : http://127.0.0.1:5173\n'
  printf '  admin UI    : http://127.0.0.1:5174\n'
  printf '\n'
  printf '%b  Admin login%b\n' "${C_BOLD}" "${C_RESET}"
  printf '    email    : %s\n' "${ADMIN_EMAIL}"
  printf '    password : %s\n' "${admin_pw}"
  printf '    (also stored in %s/.secrets/admin_password)\n' "${VLESSICH_DIR}"
  printf '\n'
  if [[ -n "${PUBLIC_DOMAIN}" ]]; then
    printf '%b  Webhook setup%b\n' "${C_BOLD}" "${C_RESET}"
    printf '    1. Put Caddy/nginx in front of 127.0.0.1:8000 with TLS for %s\n' "${PUBLIC_DOMAIN}"
    printf '    2. Run: curl -X POST https://api.telegram.org/bot<TOKEN>/setWebhook \\\n'
    printf '              -d url=https://%s/telegram/webhook \\\n' "${PUBLIC_DOMAIN}"
    printf '              -d secret_token=$(grep BOT_WEBHOOK_SECRET %s/.secrets/bot.env | cut -d= -f2)\n' "${VLESSICH_DIR}"
  else
    printf '%b  Mode       %b: bot polling (no public domain set)\n' "${C_BOLD}" "${C_RESET}"
    printf '  webapp/admin: bind only on 127.0.0.1 — open via SSH tunnel:\n'
    printf '     ssh -L 5174:127.0.0.1:5174 -L 5173:127.0.0.1:5173 user@host\n'
  fi
  printf '\n'
  printf '%b  Useful commands%b\n' "${C_BOLD}" "${C_RESET}"
  printf '    cd %s\n' "${VLESSICH_DIR}"
  printf '    docker compose -f docker-compose.prod.yml ps\n'
  printf '    docker compose -f docker-compose.prod.yml logs -f api\n'
  printf '    docker compose -f docker-compose.prod.yml restart api bot\n'
  printf '\n'
  printf '%b  Update / re-run%b: sudo bash %s/scripts/install.sh\n' "${C_BOLD}" "${C_RESET}" "${VLESSICH_DIR}"
  printf '\n'
}

# ---------- main ----------
main() {
  log "Vlessich one-liner installer (stage-13)"
  preflight
  install_apt_deps
  install_docker
  prompt_inputs
  clone_or_update_repo
  write_secrets
  render_env_files
  compose_up
  bootstrap_admin
  final_report
  ok "done"
}

main "$@"
