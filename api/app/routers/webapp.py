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
from app.config import get_settings
from app.db import get_session
from app.errors import ApiCode, api_error
from app.models import Device, Subscription, User
from app.schemas import (
    WebappBootstrapOut,
    WebappDeviceOut,
    WebappSubscriptionOut,
    WebappSubscriptionSummary,
    WebappUserOut,
)
from app.services.sub_urls import build_sub_urls

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


@router.get("/subscription", response_model=WebappSubscriptionOut)
async def get_subscription(
    init: Annotated[TelegramInitData, Depends(get_init_data)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WebappSubscriptionOut:
    sub = (
        await session.execute(
            select(Subscription)
            .where(
                Subscription.user_id == init.user_id,
                Subscription.status.in_(("ACTIVE", "TRIAL")),
            )
            .order_by(Subscription.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            ApiCode.NO_SUBSCRIPTION,
            "no active subscription",
        )
    devices = (
        await session.execute(
            select(Device).where(Device.subscription_id == sub.id)
        )
    ).scalars().all()
    settings = get_settings()
    return WebappSubscriptionOut(
        id=str(sub.id),
        plan=sub.plan,
        status=sub.status,
        expires_at=sub.expires_at,
        sub_token=sub.sub_url_token,
        urls=build_sub_urls(sub.sub_url_token, settings.sub_worker_base_url),
        devices=[
            WebappDeviceOut(
                id=str(d.id),
                name=d.name,
                last_seen=d.last_seen,
                ip_hash_short=(d.ip_hash[:12] if d.ip_hash else None),
            )
            for d in devices
        ],
        devices_limit=sub.devices_limit,
        adblock=sub.adblock,
        smart_routing=sub.smart_routing,
    )
