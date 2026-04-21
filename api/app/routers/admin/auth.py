"""Admin auth router: login (POST /admin/auth/login).

Rate-limited per email via Redis sliding window (10/min). Failed attempts
are recorded in ``admin_login_attempts`` for audit, successes bump
``admin_users.last_login_at``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import Role, create_access_token, verify_password
from app.db import get_session
from app.errors import ApiCode, api_error
from app.metrics import ADMIN_LOGIN_TOTAL
from app.models import AdminLoginAttempt, AdminUser
from app.ratelimit import sliding_window_check


class AdminLoginIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=256)


class AdminLoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


router = APIRouter(prefix="/admin/auth", tags=["admin"])


@router.post("/login", response_model=AdminLoginOut)
async def admin_login(
    body: AdminLoginIn,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AdminLoginOut:
    # Rate-limit by email (10 per 60s). Prevents brute force.
    allowed = await sliding_window_check(
        key=f"rl:admin_login:{body.email.lower()}",
        limit=10,
        window_sec=60,
    )
    if not allowed:
        ADMIN_LOGIN_TOTAL.labels(result="rate_limited").inc()
        raise api_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ApiCode.RATE_LIMITED,
            "too many login attempts",
        )

    admin = (
        await session.execute(
            select(AdminUser).where(
                AdminUser.email == body.email,
                AdminUser.status == "ACTIVE",
            )
        )
    ).scalar_one_or_none()

    ok = admin is not None and verify_password(body.password, admin.password_hash)

    async with session.begin():
        session.add(
            AdminLoginAttempt(
                email=body.email.lower(),
                success=ok,
                ip_hash=None,  # IP hashing is caller's concern (see TZ §14)
            )
        )
        if ok and admin is not None:
            admin.last_login_at = datetime.now(timezone.utc)

    if not ok or admin is None:
        ADMIN_LOGIN_TOTAL.labels(result="fail").inc()
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, ApiCode.BAD_SIG, "invalid credentials"
        )

    role_value = admin.role
    if role_value not in ("superadmin", "support", "readonly"):
        raise api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            ApiCode.INTERNAL,
            "admin role corrupted",
        )
    role_typed = cast(Role, role_value)
    token = create_access_token(str(admin.id), role_typed)
    ADMIN_LOGIN_TOTAL.labels(result="success").inc()
    return AdminLoginOut(access_token=token, role=role_typed)
