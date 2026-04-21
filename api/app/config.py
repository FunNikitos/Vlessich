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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.model_validate({})
