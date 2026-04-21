"""Mini-App webapp endpoints (Stage 3).

All endpoints authenticate via Telegram ``initData`` (see
:mod:`app.auth.telegram`). No HMAC — this is user-facing surface.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.telegram import TelegramInitData, get_init_data
from app.db import get_session
from app.errors import ApiCode, api_error
from app.models import Subscription, User
from app.schemas import (
    WebappBootstrapOut,
    WebappSubscriptionSummary,
    WebappUserOut,
)

router = APIRouter(prefix="/v1/webapp", tags=["webapp"])


@router.get("/bootstrap", response_model=WebappBootstrapOut)
async def bootstrap(
    init: Annotated[TelegramInitData, Depends(get_init_data)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WebappBootstrapOut:
    user = (
        await session.execute(select(User).where(User.tg_id == init.user_id))
    ).scalar_one_or_none()
    if user is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiCode.USER_NOT_FOUND, "user not found"
        )
    sub = (
        await session.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user.tg_id,
                Subscription.status.in_(("ACTIVE", "TRIAL")),
            )
            .order_by(Subscription.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    sub_out: WebappSubscriptionSummary | None = None
    if sub is not None:
        sub_out = WebappSubscriptionSummary(
            id=str(sub.id),
            plan=sub.plan,
            status=sub.status,
            expires_at=sub.expires_at,
            adblock=sub.adblock,
            smart_routing=sub.smart_routing,
        )
    return WebappBootstrapOut(
        user=WebappUserOut(
            tg_id=user.tg_id,
            username=user.tg_username,
            first_name=init.first_name,
        ),
        subscription=sub_out,
    )
