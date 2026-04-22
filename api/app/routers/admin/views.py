"""Admin read-only endpoints: users / subscriptions / audit (Stage 2 T6)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import AdminClaims, require_admin_role
from app.db import get_session
from app.models import AuditLog, Subscription, User

users_router = APIRouter(prefix="/admin/users", tags=["admin"])
subs_router = APIRouter(prefix="/admin/subscriptions", tags=["admin"])
audit_router = APIRouter(prefix="/admin/audit", tags=["admin"])

_READ_ROLES = ("superadmin", "support", "readonly")


class UserOut(BaseModel):
    tg_id: int
    tg_username: str | None
    lang: str
    phone_e164: str | None
    referral_source: str | None
    banned: bool
    created_at: datetime


class UserListOut(BaseModel):
    total: int
    items: list[UserOut]


class SubscriptionAdminOut(BaseModel):
    id: UUID
    user_id: int
    plan: str
    status: str
    started_at: datetime
    expires_at: datetime | None
    devices_limit: int


class SubscriptionListOut(BaseModel):
    total: int
    items: list[SubscriptionAdminOut]


class AuditOut(BaseModel):
    id: UUID
    actor_type: str
    actor_ref: str | None
    action: str
    target_type: str | None
    target_id: str | None
    at: datetime


class AuditListOut(BaseModel):
    total: int
    items: list[AuditOut]


@users_router.get("", response_model=UserListOut)
async def list_users(
    session: Annotated[AsyncSession, Depends(get_session)],
    _claims: Annotated[AdminClaims, Depends(require_admin_role(*_READ_ROLES))],
    tg_id: int | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> UserListOut:
    stmt = select(User).order_by(User.created_at.desc())
    if tg_id is not None:
        stmt = stmt.where(User.tg_id == tg_id)
    total = len((await session.execute(stmt.with_only_columns(User.tg_id))).all())
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    items = [
        UserOut(
            tg_id=u.tg_id,
            tg_username=u.tg_username,
            lang=u.lang,
            phone_e164=u.phone_e164,
            referral_source=u.referral_source,
            banned=u.banned,
            created_at=u.created_at,
        )
        for u in rows
    ]
    return UserListOut(total=total, items=items)


@subs_router.get("", response_model=SubscriptionListOut)
async def list_subscriptions(
    session: Annotated[AsyncSession, Depends(get_session)],
    _claims: Annotated[AdminClaims, Depends(require_admin_role(*_READ_ROLES))],
    status_filter: Annotated[
        Literal["ACTIVE", "TRIAL", "EXPIRED", "REVOKED"] | None,
        Query(alias="status"),
    ] = None,
    plan: str | None = None,
    user_id: int | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> SubscriptionListOut:
    stmt = select(Subscription).order_by(Subscription.started_at.desc())
    if status_filter is not None:
        stmt = stmt.where(Subscription.status == status_filter)
    if plan is not None:
        stmt = stmt.where(Subscription.plan == plan)
    if user_id is not None:
        stmt = stmt.where(Subscription.user_id == user_id)
    total = len(
        (await session.execute(stmt.with_only_columns(Subscription.id))).all()
    )
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    items = [
        SubscriptionAdminOut(
            id=s.id,
            user_id=s.user_id,
            plan=s.plan,
            status=s.status,
            started_at=s.started_at,
            expires_at=s.expires_at,
            devices_limit=s.devices_limit,
        )
        for s in rows
    ]
    return SubscriptionListOut(total=total, items=items)


@audit_router.get("", response_model=AuditListOut)
async def list_audit(
    session: Annotated[AsyncSession, Depends(get_session)],
    _claims: Annotated[AdminClaims, Depends(require_admin_role(*_READ_ROLES))],
    action: str | None = None,
    actor_type: Literal["system", "admin", "user", "bot"] | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
) -> AuditListOut:
    stmt = select(AuditLog).order_by(AuditLog.at.desc())
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if actor_type is not None:
        stmt = stmt.where(AuditLog.actor_type == actor_type)
    total = len((await session.execute(stmt.with_only_columns(AuditLog.id))).all())
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    items = [
        AuditOut(
            id=a.id,
            actor_type=a.actor_type,
            actor_ref=a.actor_ref,
            action=a.action,
            target_type=a.target_type,
            target_id=a.target_id,
            at=a.at,
        )
        for a in rows
    ]
    return AuditListOut(total=total, items=items)
