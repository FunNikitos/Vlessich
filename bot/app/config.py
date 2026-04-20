"""Runtime settings (12-factor, pydantic-settings).

All secrets are injected via environment variables. No .env in production
containers; dev uses ``.env.dev`` mounted read-only.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env.dev", ".env"),
        env_prefix="BOT_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "staging", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Telegram
    token: SecretStr = Field(..., description="Telegram bot token from @BotFather")
    webhook_url: HttpUrl | None = Field(
        default=None,
        description="If set, bot runs in webhook mode; otherwise long-polling",
    )
    webhook_secret: SecretStr | None = None
    webhook_path: str = "/telegram/webhook"
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080

    # Backend
    api_base_url: HttpUrl = Field(..., description="Vlessich backend API base URL")
    api_internal_secret: SecretStr = Field(
        ..., description="HMAC secret shared with backend"
    )

    # Infra
    redis_url: str = "redis://redis:6379/0"

    # UX
    webapp_url: HttpUrl | None = None
    support_username: str = "vlessich_support"

    @property
    def use_webhook(self) -> bool:
        return self.webhook_url is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
