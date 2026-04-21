"""Admin endpoints: codes CRUD (Stage 2 T6).

Write (POST/DELETE) requires ``support`` or ``superadmin`` — DELETE is
restricted to ``superadmin``. Reads are open to all three roles.
"""
from __future__ import annotations

import hashlib
import secrets
import string
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import AdminClaims, require_admin_role
from app.crypto import get_cipher
from app.db import get_session
from app.errors import ApiCode, api_error
from app.models import AuditLog, Code

router = APIRouter(prefix="/admin/codes", tags=["admin"])


class CodeOut(BaseModel):
    id: UUID
    plan_name: str
    duration_days: int
    devices_limit: int
    status: str
    valid_from: datetime
    valid_until: datetime
    reserved_for_tg_id: int | None
    tag: str | None
    note: str | None
    created_at: datetime


class CodeBatchCreateIn(BaseModel):
    plan_name: str = Field(..., min_length=1, max_length=64)
    duration_days: int = Field(..., gt=0, le=3650)
    devices_limit: int = Field(..., gt=0, le=10)
    traffic_limit_gb: int | None = Field(default=None, ge=0)
    allowed_locations: list[str] = Field(default_factory=lambda: ["fi"])
    count: int = Field(..., gt=0, le=1000)
    valid_days: int = Field(default=365, gt=0, le=3650)
    reserved_for_tg_id: int | None = None
    tag: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=256)


class CodeBatchCreateOut(BaseModel):
    created: int
    codes: list[str]  # plaintext returned ONCE at creation time


class CodeListOut(BaseModel):
    total: int
    items: list[CodeOut]


_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _generate_code(length: int = 12) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


@router.get("", response_model=CodeListOut)
async def list_codes(
    session: Annotated[AsyncSession, Depends(get_session)],
    _claims: Annotated[
        AdminClaims, Depends(require_admin_role("superadmin", "support", "readonly"))
    ],
    status_filter: Annotated[
        Literal["ACTIVE", "USED", "REVOKED", "EXPIRED"] | None,
        Query(alias="status"),
    ] = None,
    plan: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> CodeListOut:
    stmt = select(Code).order_by(Code.created_at.desc())
    if status_filter is not None:
        stmt = stmt.where(Code.status == status_filter)
    if plan is not None:
        stmt = stmt.where(Code.plan_name == plan)
    total_stmt = stmt.with_only_columns(Code.id)
    total = len((await session.execute(total_stmt)).all())
    stmt = stmt.offset((page - 1) * limit).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    items = [
        CodeOut(
            id=c.id,
            plan_name=c.plan_name,
            duration_days=c.duration_days,
            devices_limit=c.devices_limit,
            status=c.status,
            valid_from=c.valid_from,
            valid_until=c.valid_until,
            reserved_for_tg_id=c.reserved_for_tg_id,
            tag=c.tag,
            note=c.note,
            created_at=c.created_at,
        )
        for c in rows
    ]
    return CodeListOut(total=total, items=items)


@router.post("", response_model=CodeBatchCreateOut, status_code=status.HTTP_201_CREATED)
async def create_codes(
    body: CodeBatchCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    claims: Annotated[AdminClaims, Depends(require_admin_role("superadmin", "support"))],
) -> CodeBatchCreateOut:
    cipher = get_cipher()
    now = datetime.now(UTC)
    valid_until = now + timedelta(days=body.valid_days)
    plaintexts: list[str] = []
    async with session.begin():
        for _ in range(body.count):
            raw = _generate_code()
            plaintexts.append(raw)
            session.add(
                Code(
                    code_enc=cipher.seal(raw),
                    code_hash=hashlib.sha256(raw.encode()).hexdigest(),
                    plan_name=body.plan_name,
                    duration_days=body.duration_days,
                    devices_limit=body.devices_limit,
                    traffic_limit_gb=body.traffic_limit_gb,
                    allowed_locations=body.allowed_locations,
                    valid_from=now,
                    valid_until=valid_until,
                    reserved_for_tg_id=body.reserved_for_tg_id,
                    tag=body.tag,
                    note=body.note,
                )
            )
        session.add(
            AuditLog(
                actor_type="admin",
                actor_ref=claims.sub,
                action="admin_codes_created",
                target_type="code_batch",
                target_id=None,
                payload={
                    "count": body.count,
                    "plan": body.plan_name,
                    "duration_days": body.duration_days,
                },
            )
        )
    return CodeBatchCreateOut(created=body.count, codes=plaintexts)


@router.delete("/{code_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_code(
    code_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    claims: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> None:
    async with session.begin():
        code = await session.scalar(
            select(Code).where(Code.id == code_id).with_for_update()
        )
        if code is None:
            raise api_error(
                status.HTTP_404_NOT_FOUND, ApiCode.CODE_NOT_FOUND, "code not found"
            )
        if code.status == "REVOKED":
            return None
        code.status = "REVOKED"
        code.revoked_at = datetime.now(UTC)
        session.add(
            AuditLog(
                actor_type="admin",
                actor_ref=claims.sub,
                action="admin_code_revoked",
                target_type="code",
                target_id=str(code_id),
                payload=None,
            )
        )
    return None
