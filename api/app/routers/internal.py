"""Internal sub-Worker endpoint (TZ §11A.3).

Called from Cloudflare Worker ``sub.<domain>/*`` to fetch subscription payload
by opaque token. HMAC-signed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.security import verify_internal_signature

router = APIRouter(
    prefix="/internal/sub",
    tags=["internal"],
    dependencies=[Depends(verify_internal_signature)],
)


@router.get("/{token}")
async def get_sub(token: str) -> dict[str, object]:
    # TODO: lookup subscriptions.sub_url_token == token, compose payload.
    if len(token) < 32 or len(token) > 128:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return {
        "sub_url_token": token,
        "plan": "TODO",
        "expires_at": None,
        "inbounds": [],
    }
