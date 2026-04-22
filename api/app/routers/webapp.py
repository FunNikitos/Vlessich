"""Mini-App webapp endpoints (Stage 3).

All endpoints authenticate via Telegram ``initData`` (see
:mod:`app.auth.telegram`). No HMAC — this is user-facing surface.
"""
from __future__ import annotations

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.telegram import TelegramInitData, get_init_data
from app.config import get_settings
from app.crypto import get_cipher
from app.db import get_session
from app.errors import ApiCode, api_error
from app.models import AuditLog, Device, Subscription, User
from app.ratelimit import sliding_window_check
from app.schemas import (
    WebappBootstrapOut,
    WebappDeviceOut,
    WebappDeviceResetOut,
    WebappSubscriptionOut,
    WebappSubscriptionSummary,
    WebappToggleIn,
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


async def _load_user_subscription(
    session: AsyncSession, tg_id: int
) -> Subscription:
    sub = (
        await session.execute(
            select(Subscription)
            .where(
                Subscription.user_id == tg_id,
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
    return sub


@router.post("/subscription/toggle")
async def toggle_routing(
    body: WebappToggleIn,
    init: Annotated[TelegramInitData, Depends(get_init_data)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, bool]:
    if body.adblock is None and body.smart_routing is None:
        raise api_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            ApiCode.INVALID_REQUEST,
            "at least one of adblock/smart_routing required",
        )
    sub = await _load_user_subscription(session, init.user_id)
    async with session.begin():
        if body.adblock is not None:
            sub.adblock = body.adblock
        if body.smart_routing is not None:
            sub.smart_routing = body.smart_routing
        session.add(
            AuditLog(
                actor_type="user",
                actor_ref=str(init.user_id),
                action="webapp_toggle_routing",
                target_type="subscription",
                target_id=str(sub.id),
                payload={
                    "adblock": body.adblock,
                    "smart_routing": body.smart_routing,
                },
            )
        )
    return {"adblock": sub.adblock, "smart_routing": sub.smart_routing}


@router.post(
    "/devices/{device_id}/reset", response_model=WebappDeviceResetOut
)
async def reset_device(
    device_id: UUID,
    init: Annotated[TelegramInitData, Depends(get_init_data)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WebappDeviceResetOut:
    allowed = await sliding_window_check(
        key=f"rl:webapp:reset:{init.user_id}", limit=5, window_sec=60
    )
    if not allowed:
        raise api_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ApiCode.RATE_LIMITED,
            "too many reset attempts",
        )
    device = (
        await session.execute(select(Device).where(Device.id == device_id))
    ).scalar_one_or_none()
    if device is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiCode.INVALID_REQUEST, "device not found"
        )
    sub = (
        await session.execute(
            select(Subscription).where(Subscription.id == device.subscription_id)
        )
    ).scalar_one_or_none()
    if sub is None or sub.user_id != init.user_id:
        raise api_error(
            status.HTTP_403_FORBIDDEN, ApiCode.FORBIDDEN, "device not owned by user"
        )
    new_uuid = secrets.token_hex(16)  # 32-char hex stand-in for UUID
    cipher = get_cipher()
    async with session.begin():
        device.xray_uuid_enc = cipher.seal(new_uuid)
        session.add(
            AuditLog(
                actor_type="user",
                actor_ref=str(init.user_id),
                action="webapp_device_reset",
                target_type="device",
                target_id=str(device.id),
                payload={"sub_id": str(sub.id)},
            )
        )
    return WebappDeviceResetOut(
        device_id=str(device.id), new_uuid_suffix=new_uuid[-4:]
    )
