"""Admin stats endpoint (Stage 4 T1).

Aggregates counts for the admin dashboard. Open to all admin roles.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import AdminClaims, require_admin_role
from app.db import get_session
from app.models import Code, Node, Subscription, User
from app.schemas import StatsOut

router = APIRouter(prefix="/admin/stats", tags=["admin"])

_READ_ROLES = ("superadmin", "support", "readonly")
_STALE_AFTER = timedelta(minutes=5)


@router.get("", response_model=StatsOut)
async def get_stats(
    session: Annotated[AsyncSession, Depends(get_session)],
    _claims: Annotated[AdminClaims, Depends(require_admin_role(*_READ_ROLES))],
) -> StatsOut:
    users_total = await session.scalar(select(func.count()).select_from(User)) or 0

    codes_total = await session.scalar(select(func.count()).select_from(Code)) or 0
    codes_unused = (
        await session.scalar(
            select(func.count()).select_from(Code).where(Code.status == "ACTIVE")
        )
        or 0
    )

    subs_active = (
        await session.scalar(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.status == "ACTIVE")
        )
        or 0
    )
    subs_trial = (
        await session.scalar(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.status == "TRIAL")
        )
        or 0
    )

    nodes_total = await session.scalar(select(func.count()).select_from(Node)) or 0
    nodes_healthy = (
        await session.scalar(
            select(func.count()).select_from(Node).where(Node.status == "HEALTHY")
        )
        or 0
    )
    nodes_burned = (
        await session.scalar(
            select(func.count()).select_from(Node).where(Node.status == "BURNED")
        )
        or 0
    )
    nodes_maintenance = (
        await session.scalar(
            select(func.count())
            .select_from(Node)
            .where(Node.status == "MAINTENANCE")
        )
        or 0
    )

    stale_cutoff = datetime.now(UTC) - _STALE_AFTER
    nodes_stale = (
        await session.scalar(
            select(func.count())
            .select_from(Node)
            .where(
                (Node.last_probe_at.is_(None))
                | (Node.last_probe_at < stale_cutoff)
            )
        )
        or 0
    )

    return StatsOut(
        users_total=int(users_total),
        codes_total=int(codes_total),
        codes_unused=int(codes_unused),
        subs_active=int(subs_active),
        subs_trial=int(subs_trial),
        nodes_total=int(nodes_total),
        nodes_healthy=int(nodes_healthy),
        nodes_burned=int(nodes_burned),
        nodes_maintenance=int(nodes_maintenance),
        nodes_stale=int(nodes_stale),
    )
