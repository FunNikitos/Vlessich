"""Internal sub-Worker endpoint (TZ §11A.3).

Called from Cloudflare Worker ``sub.<domain>/*`` to fetch subscription payload
by opaque token. HMAC-signed with the unified wire-format shared by bot↔api
and sub-Worker↔api: ``METHOD\\npath\\nts\\n`` + raw_body.

For GET requests raw_body is empty. The Worker MUST sign the exact request
path (``/internal/sub/{token}``) with ``""`` body.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.errors import ApiCode, api_error
from app.models import Subscription
from app.security import verify_internal_signature
from app.services.sub_payload import PayloadError, build_payload

router = APIRouter(
    prefix="/internal/sub",
    tags=["internal"],
    dependencies=[Depends(verify_internal_signature)],
)


@router.get("/{token}")
async def get_sub(
    token: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    if len(token) < 16 or len(token) > 128:
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiCode.NO_SUBSCRIPTION, "subscription not found"
        )

    stmt = select(Subscription).where(
        Subscription.sub_url_token == token,
        Subscription.status.in_(("ACTIVE", "TRIAL")),
    )
    sub = (await session.execute(stmt)).scalar_one_or_none()
    if sub is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiCode.NO_SUBSCRIPTION, "subscription not found"
        )

    # Payload composer (full inbounds[]) lands in T2. For T1 we surface the
    # minimum useful shape: status/plan/expires_at so Worker can short-circuit
    # expired tokens without fetching inbounds.
    now = datetime.now(timezone.utc)
    if sub.expires_at is not None and sub.expires_at <= now:
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiCode.NO_SUBSCRIPTION, "subscription expired"
        )

    # Payload composer (T2): load nodes + devices + inbounds[].
    try:
        payload = await build_payload(session, sub.id)
    except PayloadError as exc:
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiCode.INTERNAL,
            "payload composition failed",
        ) from exc

    return {
        "sub_url_token": token,
        "status": sub.status,
        "plan": sub.plan,
        "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
        "devices_limit": sub.devices_limit,
        "inbounds": payload["inbounds"],
        "meta": payload["meta"],
    }
