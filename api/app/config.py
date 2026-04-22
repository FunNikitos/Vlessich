"""Settings (12-factor)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.dev", ".env"),
        env_prefix="API_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # DB / cache
    database_url: str = Field(
        default="postgresql+asyncpg://vlessich:vlessich@db:5432/vlessich"
    )
    redis_url: str = "redis://redis:6379/1"

    # Secrets
    internal_secret: SecretStr = Field(
        ..., description="HMAC secret for internal endpoints (bot, sub-Worker)"
    )
    secretbox_key: SecretStr = Field(
        ..., description="32-byte hex key for libsodium secretbox (Xray UUID at rest)"
    )
    fp_salt: SecretStr = Field(
        default=SecretStr("dev-fp-salt-change-me"),
        description="Salt for trial fingerprint (sha256(phone+tg_id+salt))",
    )
    ip_salt: SecretStr = Field(
        default=SecretStr("dev-ip-salt-change-me"),
        description="Salt for client IP hashing in logs/audit",
    )

    # Trial policy
    trial_days: int = Field(default=3, gt=0, le=30)

    # Code activation policy
    code_rl_attempts: int = Field(default=5, gt=0)
    code_rl_window_sec: int = Field(default=600, gt=0)

    # MTProto
    mtg_cloak_domains: list[str] = Field(
        default_factory=lambda: ["www.google.com", "www.cloudflare.com"]
    )
    mtg_host: str = "mtp.example.com"
    mtg_port: int = 443
    # Stage 8: bootstrap a single shared MtprotoSecret on API startup so
    # /internal/mtproto/issue (scope='shared') has something to hand
    # out without manual seeding. Unset → seed skipped (dev). Format:
    # 32 lowercase hex chars (matches mtg secret body without the 'ee'
    # prefix and cloak suffix — those are derived from cloak below).
    mtg_shared_secret_hex: SecretStr | None = Field(
        default=None,
        description="Shared MTProto secret (32 hex chars) seeded at startup.",
    )
    mtg_shared_cloak: str = Field(
        default="www.microsoft.com",
        description="Cloak domain bound to the seeded shared secret.",
    )

    # Stage 9: per-user MTProto secrets. When disabled, scope='user'
    # in /internal/mtproto/issue returns 501 per_user_disabled. When
    # enabled, the allocator binds each user to a free port in the
    # range [port_base, port_base + pool_size). Operator must run
    # `pool_size` mtg containers on those ports (see ansible/roles/mtg).
    mtg_per_user_enabled: bool = Field(
        default=False,
        description="Feature flag for per-user MTProto secret allocator.",
    )
    mtg_per_user_pool_size: int = Field(
        default=16,
        ge=1,
        le=512,
        description="Number of mtg containers / ports available for per-user secrets.",
    )
    mtg_per_user_port_base: int = Field(
        default=8443,
        ge=1,
        le=65535,
        description="First port of the per-user pool (inclusive).",
    )

    # Stage 10: cron auto-rotation of the shared MTProto secret. Off by
    # default; enable per-env after smoke-testing the broadcaster.
    mtg_auto_rotation_enabled: bool = Field(
        default=False,
        description="Enable cron-based rotation of ACTIVE shared MTProto secret by age.",
    )
    mtg_shared_rotation_days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Rotate ACTIVE shared MTProto secret older than N days.",
    )
    mtg_rotator_interval_sec: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Seconds between mtproto_rotator worker ticks.",
    )

    # Stage 10: deeplink rebroadcast pipeline. API XADDs a rotation event
    # to Redis stream `mtproto:rotated`; broadcaster worker fans out to
    # affected users via bot HTTP endpoint.
    mtg_broadcast_enabled: bool = Field(
        default=False,
        description="Master switch for emitting and consuming MTProto rotation broadcast events.",
    )
    mtg_broadcast_cooldown_sec: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Minimum seconds between two broadcast DMs to the same Telegram chat.",
    )
    mtg_broadcast_idempotency_ttl_sec: int = Field(
        default=86400,
        ge=3600,
        le=604800,
        description="TTL of (event_id, tg_id) idempotency marker in Redis.",
    )
    mtg_broadcast_rl_global_per_sec: int = Field(
        default=30,
        ge=1,
        le=30,
        description="Global broadcast rate-limit (Telegram bot ceiling is 30 msg/s).",
    )
    mtg_broadcast_rl_per_chat_sec: int = Field(
        default=1,
        ge=1,
        le=60,
        description="Minimum seconds between two messages to the same chat (Telegram per-chat limit).",
    )
    mtg_broadcast_stream_maxlen: int = Field(
        default=10000,
        ge=100,
        le=1000000,
        description="Approximate XADD MAXLEN for the mtproto:rotated stream.",
    )
    mtg_broadcast_bot_notify_url: str = Field(
        default="http://bot:8081/internal/notify/mtproto_rotated",
        description="Bot HTTP endpoint that broadcaster calls with HMAC-signed payload.",
    )

    # Telegram
    bot_token: SecretStr | None = None  # для серверной валидации Mini-App initData

    # CORS / public
    public_base_url: str = "https://api.example.com"
    cors_origins: list[str] = Field(default_factory=list)

    # Remnawave / VPN backend (TZ §10)
    remnawave_mode: Literal["mock", "http"] = "mock"
    remnawave_url: str = "http://remnawave:3000"
    remnawave_token: SecretStr | None = None

    # sub-Worker public base URL (Stage 3, Mini-App webapp endpoint)
    sub_worker_base_url: str = Field(
        default="https://sub.example.com",
        description="Public sub-Worker base URL shown to VPN clients",
    )

    # Admin API (Stage 2 T4)
    admin_jwt_secret: SecretStr = Field(
        default=SecretStr("dev-admin-jwt-change-me"),
        description="HS256 secret for admin JWT (separate from internal_secret)",
    )
    admin_jwt_ttl_sec: int = Field(default=3600, gt=0)
    admin_bcrypt_cost: int = Field(default=12, ge=4, le=15)

    # Active probing (Stage 5)
    probe_interval_sec: int = Field(
        default=60, gt=0, description="Seconds between prober ticks"
    )
    probe_timeout_sec: float = Field(
        default=5.0, gt=0, description="Per-node TCP connect timeout (seconds)"
    )
    probe_port: int = Field(
        default=443, gt=0, le=65535, description="TCP port probed on each node"
    )
    probe_burn_threshold: int = Field(
        default=3, gt=0, description="Consecutive failures to mark node BURNED"
    )
    probe_recover_threshold: int = Field(
        default=5,
        gt=0,
        description="Consecutive successes to recover BURNED → HEALTHY",
    )
    probe_metrics_port: int = Field(
        default=9101,
        gt=0,
        le=65535,
        description="Port on which prober process exposes Prometheus /metrics",
    )

    # Stage 7: second probe backend via residential RU proxy. Unset =
    # edge-only prober (default behaviour). Format:
    #   socks5://user:pass@host:port  (recommended)
    #   http://user:pass@host:port
    ru_proxy_url: str | None = Field(
        default=None,
        description="Residential RU proxy URL (enables 'ru' probe backend).",
    )
    ru_probe_timeout_sec: float = Field(
        default=8.0,
        gt=0,
        description="Per-node HTTP probe timeout via RU proxy (seconds).",
    )

    # Admin captcha (Stage 6)
    turnstile_secret: SecretStr | None = Field(
        default=None,
        description=(
            "Cloudflare Turnstile secret. If unset, captcha is disabled "
            "and admin login does not require a token (dev mode)."
        ),
    )
    turnstile_verify_url: str = Field(
        default="https://challenges.cloudflare.com/turnstile/v0/siteverify",
        description="Cloudflare Turnstile siteverify endpoint.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.model_validate({})
