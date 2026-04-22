"""Admin ruleset endpoints (Stage 12).

CRUD sources + force-pull + snapshot history. All endpoints require
JWT; CRUD/force-pull require ``superadmin``, reads allow ``support`` /
``readonly``.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import AdminClaims, require_admin_role
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiCode, api_error
from app.models import RulesetSnapshot, RulesetSource
from app.schemas import (
    RulesetSnapshotAdminOut,
    RulesetSourceCreateIn,
    RulesetSourceOut,
    RulesetSourcesListOut,
    RulesetSourceUpdateIn,
)
from app.services.ruleset.puller import http_fetcher, pull_source

log = structlog.get_logger("admin.ruleset")

router = APIRouter(prefix="/admin/ruleset", tags=["admin", "smart-routing"])

_READ_ROLES = ("superadmin", "support", "readonly")


def _to_out(src: RulesetSource, current_count: int | None) -> RulesetSourceOut:
    return RulesetSourceOut(
        id=str(src.id),
        name=src.name,
        kind=src.kind,  # type: ignore[arg-type]
        url=src.url,
        category=src.category,  # type: ignore[arg-type]
        is_enabled=src.is_enabled,
        last_pulled_at=src.last_pulled_at,
        last_error=src.last_error,
        current_domain_count=current_count,
    )


@router.get("/sources", response_model=RulesetSourcesListOut)
async def list_sources(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AdminClaims, Depends(require_admin_role(*_READ_ROLES))],
) -> RulesetSourcesListOut:
    sources = (
        await session.execute(select(RulesetSource).order_by(RulesetSource.name))
    ).scalars().all()
    # Fetch current snapshot counts in one round-trip.
    snaps = (
        await session.execute(
            select(RulesetSnapshot.source_id, RulesetSnapshot.domain_count).where(
                RulesetSnapshot.is_current.is_(True)
            )
        )
    ).all()
    counts = {sid: cnt for sid, cnt in snaps}
    return RulesetSourcesListOut(
        items=[_to_out(s, counts.get(s.id)) for s in sources]
    )


@router.post(
    "/sources",
    response_model=RulesetSourceOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_source(
    payload: RulesetSourceCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> RulesetSourceOut:
    if payload.kind != "custom" and not payload.url:
        raise api_error(
            status.HTTP_400_BAD_REQUEST,
            ApiCode.INVALID_REQUEST,
            "url is required for non-custom sources",
        )
    existing = await session.scalar(
        select(RulesetSource).where(RulesetSource.name == payload.name)
    )
    if existing is not None:
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiCode.INVALID_REQUEST,
            "source with that name already exists",
        )
    src = RulesetSource(
        name=payload.name,
        kind=payload.kind,
        url=payload.url,
        category=payload.category,
        is_enabled=payload.is_enabled,
    )
    session.add(src)
    await session.flush()
    return _to_out(src, None)


@router.patch("/sources/{source_id}", response_model=RulesetSourceOut)
async def update_source(
    source_id: UUID,
    payload: RulesetSourceUpdateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> RulesetSourceOut:
    src = await session.scalar(
        select(RulesetSource).where(RulesetSource.id == source_id)
    )
    if src is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            ApiCode.RULESET_NOT_FOUND,
            "ruleset source not found",
        )
    if payload.url is not None:
        src.url = payload.url
    if payload.is_enabled is not None:
        src.is_enabled = payload.is_enabled
    if payload.category is not None:
        src.category = payload.category
    await session.flush()
    return _to_out(src, None)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> None:
    src = await session.scalar(
        select(RulesetSource).where(RulesetSource.id == source_id)
    )
    if src is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            ApiCode.RULESET_NOT_FOUND,
            "ruleset source not found",
        )
    await session.delete(src)


@router.post("/sources/{source_id}/pull", response_model=RulesetSourceOut)
async def force_pull(
    source_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> RulesetSourceOut:
    src = await session.scalar(
        select(RulesetSource).where(RulesetSource.id == source_id)
    )
    if src is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            ApiCode.RULESET_NOT_FOUND,
            "ruleset source not found",
        )
    if not src.is_enabled:
        raise api_error(
            status.HTTP_409_CONFLICT,
            ApiCode.RULESET_SOURCE_DISABLED,
            "source is disabled",
        )
    outcome = await pull_source(
        session,
        src,
        fetcher=http_fetcher,
        timeout_sec=settings.ruleset_http_timeout_sec,
    )
    if outcome.result == "error":
        raise api_error(
            status.HTTP_502_BAD_GATEWAY,
            ApiCode.RULESET_PULL_FAILED,
            outcome.error or "pull failed",
        )
    return _to_out(src, outcome.domain_count or None)


@router.get(
    "/sources/{source_id}/snapshots",
    response_model=list[RulesetSnapshotAdminOut],
)
async def list_snapshots(
    source_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[AdminClaims, Depends(require_admin_role(*_READ_ROLES))],
) -> list[RulesetSnapshotAdminOut]:
    src = await session.scalar(
        select(RulesetSource).where(RulesetSource.id == source_id)
    )
    if src is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND,
            ApiCode.RULESET_NOT_FOUND,
            "ruleset source not found",
        )
    rows = (
        await session.scalars(
            select(RulesetSnapshot)
            .where(RulesetSnapshot.source_id == source_id)
            .order_by(RulesetSnapshot.fetched_at.desc())
            .limit(50)
        )
    ).all()
    return [
        RulesetSnapshotAdminOut(
            id=str(r.id),
            source_id=str(r.source_id),
            sha256=r.sha256,
            domain_count=r.domain_count,
            is_current=r.is_current,
            fetched_at=r.fetched_at,
        )
        for r in rows
    ]
