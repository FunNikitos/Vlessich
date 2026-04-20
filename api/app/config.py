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

    # Telegram
    bot_token: SecretStr | None = None  # для серверной валидации Mini-App initData

    # CORS / public
    public_base_url: str = "https://api.example.com"
    cors_origins: list[str] = Field(default_factory=list)

    # Remnawave / VPN backend (TZ §10)
    remnawave_url: str = "http://remnawave:3000"
    remnawave_token: SecretStr | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
