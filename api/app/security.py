"""HMAC signature verification for internal endpoints (bot + sub-Worker).

Wire format (matches ``bot/app/services/api_client.py::ApiClient._sign``):

    msg = f"{METHOD}\\n{path}\\n{ts}\\n".encode() + raw_body
    sig = hmac.sha256(secret, msg).hexdigest()
    headers: x-vlessich-ts, x-vlessich-sig

Clock skew tolerance: ``MAX_CLOCK_SKEW_SEC``.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Header, HTTPException, Request, status

from app.config import get_settings
from app.errors import ApiCode, api_error

MAX_CLOCK_SKEW_SEC = 60


def _compute_signature(secret: bytes, method: str, path: str, ts: int, body: bytes) -> str:
    msg = f"{method.upper()}\n{path}\n{ts}\n".encode() + body
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


async def verify_internal_signature(
    request: Request,
    x_vlessich_ts: str = Header(..., alias="x-vlessich-ts"),
    x_vlessich_sig: str = Header(..., alias="x-vlessich-sig"),
) -> None:
    try:
        ts = int(x_vlessich_ts)
    except ValueError as exc:
        raise api_error(status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_SIG, "bad timestamp") from exc
    if abs(time.time() - ts) > MAX_CLOCK_SKEW_SEC:
        raise api_error(status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_SIG, "stale timestamp")

    body = await request.body()
    secret = get_settings().internal_secret.get_secret_value().encode()
    expected = _compute_signature(secret, request.method, request.url.path, ts, body)
    if not hmac.compare_digest(expected, x_vlessich_sig):
        raise api_error(status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_SIG, "bad signature")


# Keep import-time alias for compatibility with HTTPException-based callers.
__all__ = ["MAX_CLOCK_SKEW_SEC", "verify_internal_signature", "_compute_signature", "HTTPException"]
