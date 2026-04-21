"""Telegram Mini-App ``initData`` HMAC-SHA256 verification (TZ §11B).

Telegram WebApp passes a signed query string in ``window.Telegram.WebApp.initData``.
The signature scheme (per Telegram docs):

1. Split the query into ``key=value`` pairs, drop the ``hash`` field.
2. Sort the rest lexicographically and join with ``\\n`` → ``data_check_string``.
3. ``secret_key = HMAC_SHA256(key=b"WebAppData", msg=bot_token)``.
4. ``expected = HMAC_SHA256(key=secret_key, msg=data_check_string).hexdigest()``.
5. Compare to the received ``hash`` in constant time.
6. Reject if ``now - auth_date > max_age_sec`` (default 24h, per Telegram).

Webapp endpoints take the raw query string in the ``x-telegram-initdata`` header.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import parse_qsl

from fastapi import Header, status
from pydantic import SecretStr

from app.config import get_settings
from app.errors import ApiCode, api_error

INIT_DATA_MAX_AGE_SEC = 86400  # 24h, per Telegram recommendation


@dataclass(slots=True, frozen=True)
class TelegramInitData:
    user_id: int
    username: str | None
    first_name: str | None
    auth_date: int
    start_param: str | None


def _build_data_check_string(fields: dict[str, str]) -> str:
    return "\n".join(f"{k}={fields[k]}" for k in sorted(fields))


def verify_init_data(
    raw: str,
    bot_token: SecretStr,
    *,
    max_age_sec: int = INIT_DATA_MAX_AGE_SEC,
    now: int | None = None,
) -> TelegramInitData:
    """Parse + verify the raw ``initData`` query string. Raise on any failure."""
    if not raw:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_INIT_DATA, "missing init data"
        )
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=False)
    fields = dict(pairs)
    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_INIT_DATA, "missing hash"
        )
    data_check_string = _build_data_check_string(fields)
    secret_key = hmac.new(
        b"WebAppData", bot_token.get_secret_value().encode("utf-8"), hashlib.sha256
    ).digest()
    expected = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_INIT_DATA, "bad init data hash"
        )
    auth_date_raw = fields.get("auth_date")
    try:
        auth_date = int(auth_date_raw or "")
    except ValueError as exc:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_INIT_DATA, "bad auth_date"
        ) from exc
    current = int(now if now is not None else time.time())
    if current - auth_date > max_age_sec:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED,
            ApiCode.INIT_DATA_EXPIRED,
            "init data expired",
        )
    user_raw = fields.get("user")
    if not user_raw:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_INIT_DATA, "missing user field"
        )
    try:
        user_obj = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_INIT_DATA, "bad user json"
        ) from exc
    user_id = user_obj.get("id")
    if not isinstance(user_id, int):
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_INIT_DATA, "missing user.id"
        )
    username_val = user_obj.get("username")
    first_name_val = user_obj.get("first_name")
    return TelegramInitData(
        user_id=user_id,
        username=username_val if isinstance(username_val, str) else None,
        first_name=first_name_val if isinstance(first_name_val, str) else None,
        auth_date=auth_date,
        start_param=fields.get("start_param"),
    )


async def get_init_data(
    x_telegram_initdata: Annotated[str, Header(alias="x-telegram-initdata")] = "",
) -> TelegramInitData:
    """FastAPI dependency: read header + verify against configured bot_token."""
    settings = get_settings()
    if settings.bot_token is None:
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiCode.BOT_TOKEN_NOT_CONFIGURED,
            "bot token is not configured",
        )
    return verify_init_data(x_telegram_initdata, settings.bot_token)


__all__ = [
    "INIT_DATA_MAX_AGE_SEC",
    "TelegramInitData",
    "verify_init_data",
    "get_init_data",
]
