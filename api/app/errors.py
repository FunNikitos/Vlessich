"""Centralized API error envelope.

All ``HTTPException`` raised inside Vlessich API must use ``api_error`` so the
response body has a stable shape::

    {"code": "rate_limited", "message": "слишком много попыток"}

Bot's ``ApiClient`` parses ``code`` for branching and ``message`` for the user.
"""
from __future__ import annotations

from enum import StrEnum

from fastapi import HTTPException


class ApiCode(StrEnum):
    BAD_SIG = "bad_signature"
    RATE_LIMITED = "rate_limited"
    CODE_NOT_FOUND = "code_not_found"
    CODE_USED = "code_used"
    CODE_EXPIRED = "code_expired"
    CODE_RESERVED = "code_reserved"
    TRIAL_ALREADY_USED = "trial_already_used"
    NO_SUBSCRIPTION = "no_active_subscription"
    NO_SHARED_POOL = "no_shared_mtproto_pool"
    INVALID_REQUEST = "invalid_request"
    INTERNAL = "internal_error"
    BAD_INIT_DATA = "bad_init_data"
    INIT_DATA_EXPIRED = "init_data_expired"
    BOT_TOKEN_NOT_CONFIGURED = "bot_token_not_configured"
    USER_NOT_FOUND = "user_not_found"
    FORBIDDEN = "forbidden"
    SUBSCRIPTION_NOT_FOUND = "subscription_not_found"
    ALREADY_INACTIVE = "already_inactive"
    NODE_NOT_FOUND = "node_not_found"
    CAPTCHA_FAILED = "captcha_failed"
    NOT_IMPLEMENTED = "not_implemented"
    PER_USER_DISABLED = "per_user_disabled"
    POOL_FULL = "pool_full"


def api_error(status_code: int, code: ApiCode | str, message: str) -> HTTPException:
    """Build an ``HTTPException`` with the canonical ``{code, message}`` body."""
    return HTTPException(
        status_code=status_code,
        detail={"code": str(code), "message": message},
    )
