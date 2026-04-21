"""Per-user subscription lookup (TZ §7)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Subscription
from app.schemas import SubscriptionOut
from app.security import verify_internal_signature

router = APIRouter(
    prefix="/internal/users",
    tags=["internal"],
    dependencies=[Depends(verify_internal_signature)],
)


@router.get("/{tg_id}/subscription", response_model=SubscriptionOut)
async def get_subscription(
    tg_id: int,
    session: AsyncSession = Depends(get_session),
) -> SubscriptionOut:
    sub = await session.scalar(
        select(Subscription)
        .where(
            Subscription.user_id == tg_id,
            Subscription.status.in_(("ACTIVE", "TRIAL")),
        )
        .limit(1)
    )
    if sub is None:
        return SubscriptionOut(status="NONE")
    # Narrow status literal for pydantic.
    status = "TRIAL" if sub.status == "TRIAL" else "ACTIVE"
    return SubscriptionOut(
        status=status,
        plan=sub.plan,
        expires_at=sub.expires_at,
        sub_token=sub.sub_url_token,
        devices_limit=sub.devices_limit,
        traffic_limit_gb=sub.traffic_limit_gb,
        traffic_used_gb=float(sub.traffic_used_gb),
    )
