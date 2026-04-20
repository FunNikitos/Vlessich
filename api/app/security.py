"""HMAC signature verification for internal endpoints (bot + sub-Worker)."""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Header, HTTPException, Request, status

from app.config import get_settings

MAX_CLOCK_SKEW_SEC = 60


async def verify_internal_signature(
    request: Request,
    x_vlessich_ts: str = Header(..., alias="x-vlessich-ts"),
    x_vlessich_sig: str = Header(..., alias="x-vlessich-sig"),
) -> None:
    try:
        ts = int(x_vlessich_ts)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad ts") from exc
    if abs(time.time() - ts) > MAX_CLOCK_SKEW_SEC:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="stale ts")

    body = await request.body()
    method = request.method.upper()
    path = request.url.path
    secret = get_settings().internal_secret.get_secret_value().encode()
    expected = hmac.new(
        secret, f"{method}\n{path}\n{ts}\n".encode() + body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, x_vlessich_sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad signature")
