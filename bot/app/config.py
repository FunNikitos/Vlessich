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

    # Stage 10: MTProto rotation broadcast endpoint (called by api
    # `mtproto_broadcaster` worker with HMAC signature). Listens on a
    # separate aiohttp app from the Telegram webhook.
    internal_notify_enabled: bool = Field(
        default=True,
        description="Enable /internal/notify/* HTTP endpoints in bot process.",
    )
    internal_notify_host: str = "0.0.0.0"
    internal_notify_port: int = 8081
    internal_notify_path: str = "/internal/notify/mtproto_rotated"

    # Stage 11: Billing / Telegram Stars. Master flag gates the /buy
    # menu in the bot UI and the F.successful_payment handler. The
    # refund endpoint on notify_server stays available regardless so
    # admins can still issue refunds during a billing freeze.
    billing_enabled: bool = Field(
        default=False,
        description="Enable /buy menu and Telegram Stars purchase flow.",
    )
    internal_refund_path: str = Field(
        default="/internal/refund/star_payment",
        description="HMAC POST endpoint on notify_server invoked by API admin refund.",
    )

    # Stage 12: Smart-routing. Master flag gates the /config command +
    # main-menu button. Sub-Worker base URL is used to craft the
    # download deep-link handed to the user after profile switch.
    smart_routing_enabled: bool = Field(
        default=False,
        description="Enable /config command and routing profile selector.",
    )
    sub_worker_base_url: HttpUrl | None = Field(
        default=None,
        description="Public sub-Worker base URL for subscription download links.",
    )

    @property
    def use_webhook(self) -> bool:
        return self.webhook_url is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # ``model_validate({})`` forces env-based load without tripping mypy on
    # required fields (pydantic-settings reads from env, not kwargs).
    return Settings.model_validate({})
