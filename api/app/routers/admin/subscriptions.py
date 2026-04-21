"""Admin subscription mutations (Stage 4 T1): revoke.

Revoke is allowed for ``support`` and ``superadmin``. Audit logged.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import AdminClaims, require_admin_role
from app.db import get_session
from app.errors import ApiCode, api_error
from app.metrics import SUBSCRIPTION_EVENTS_TOTAL
from app.models import AuditLog, Subscription
from app.routers.admin.views import SubscriptionAdminOut

router = APIRouter(prefix="/admin/subscriptions", tags=["admin"])


@router.post(
    "/{subscription_id}/revoke",
    response_model=SubscriptionAdminOut,
)
async def revoke_subscription(
    subscription_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    claims: Annotated[
        AdminClaims, Depends(require_admin_role("superadmin", "support"))
    ],
) -> SubscriptionAdminOut:
    async with session.begin():
        sub = await session.scalar(
            select(Subscription)
            .where(Subscription.id == subscription_id)
            .with_for_update()
        )
        if sub is None:
            raise api_error(
                status.HTTP_404_NOT_FOUND,
                ApiCode.SUBSCRIPTION_NOT_FOUND,
                "subscription not found",
            )
        if sub.status in ("REVOKED", "EXPIRED"):
            raise api_error(
                status.HTTP_409_CONFLICT,
                ApiCode.ALREADY_INACTIVE,
                "subscription already inactive",
            )
        previous_status = sub.status
        sub.status = "REVOKED"
        sub.expires_at = datetime.now(UTC)
        session.add(
            AuditLog(
                actor_type="admin",
                actor_ref=claims.sub,
                action="admin_subscription_revoke",
                target_type="subscription",
                target_id=str(sub.id),
                payload={
                    "user_id": sub.user_id,
                    "plan": sub.plan,
                    "previous_status": previous_status,
                },
            )
        )
    SUBSCRIPTION_EVENTS_TOTAL.labels(event="revoked").inc()
    return SubscriptionAdminOut(
        id=sub.id,
        user_id=sub.user_id,
        plan=sub.plan,
        status=sub.status,
        started_at=sub.started_at,
        expires_at=sub.expires_at,
        devices_limit=sub.devices_limit,
    )
