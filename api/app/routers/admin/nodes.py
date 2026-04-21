"""Admin nodes management (Stage 2 T7).

Read open to all roles; create/patch restricted to ``superadmin``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import AdminClaims, require_admin_role
from app.db import get_session
from app.errors import ApiCode, api_error
from app.models import AuditLog, Node

router = APIRouter(prefix="/admin/nodes", tags=["admin"])

_READ_ROLES = ("superadmin", "support", "readonly")
NodeStatus = Literal["HEALTHY", "BURNED", "MAINTENANCE"]


class NodeOut(BaseModel):
    id: UUID
    hostname: str
    current_ip: str | None
    provider: str | None
    region: str | None
    status: str
    last_probe_at: datetime | None
    created_at: datetime


class NodeCreateIn(BaseModel):
    hostname: str = Field(..., min_length=3, max_length=255)
    current_ip: str | None = Field(default=None, max_length=45)
    provider: str | None = Field(default=None, max_length=64)
    region: str | None = Field(default=None, max_length=64)
    status: NodeStatus = "HEALTHY"


class NodePatchIn(BaseModel):
    current_ip: str | None = Field(default=None, max_length=45)
    status: NodeStatus | None = None
    region: str | None = Field(default=None, max_length=64)


@router.get("", response_model=list[NodeOut])
async def list_nodes(
    session: Annotated[AsyncSession, Depends(get_session)],
    _claims: Annotated[AdminClaims, Depends(require_admin_role(*_READ_ROLES))],
) -> list[NodeOut]:
    rows = (
        await session.execute(select(Node).order_by(Node.created_at.desc()))
    ).scalars().all()
    return [
        NodeOut(
            id=n.id,
            hostname=n.hostname,
            current_ip=n.current_ip,
            provider=n.provider,
            region=n.region,
            status=n.status,
            last_probe_at=n.last_probe_at,
            created_at=n.created_at,
        )
        for n in rows
    ]


@router.post("", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
async def create_node(
    body: NodeCreateIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    claims: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> NodeOut:
    async with session.begin():
        existing = await session.scalar(
            select(Node).where(Node.hostname == body.hostname)
        )
        if existing is not None:
            raise api_error(
                status.HTTP_409_CONFLICT,
                ApiCode.INVALID_REQUEST,
                "hostname already exists",
            )
        node = Node(
            hostname=body.hostname,
            current_ip=body.current_ip,
            provider=body.provider,
            region=body.region,
            status=body.status,
        )
        session.add(node)
        await session.flush()
        session.add(
            AuditLog(
                actor_type="admin",
                actor_ref=claims.sub,
                action="admin_node_created",
                target_type="node",
                target_id=str(node.id),
                payload={"hostname": body.hostname, "region": body.region},
            )
        )
    return NodeOut(
        id=node.id,
        hostname=node.hostname,
        current_ip=node.current_ip,
        provider=node.provider,
        region=node.region,
        status=node.status,
        last_probe_at=node.last_probe_at,
        created_at=node.created_at,
    )


@router.patch("/{node_id}", response_model=NodeOut)
async def patch_node(
    node_id: UUID,
    body: NodePatchIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    claims: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> NodeOut:
    async with session.begin():
        node = await session.scalar(
            select(Node).where(Node.id == node_id).with_for_update()
        )
        if node is None:
            raise api_error(
                status.HTTP_404_NOT_FOUND, ApiCode.INVALID_REQUEST, "node not found"
            )
        changes: dict[str, object] = {}
        if body.current_ip is not None:
            node.current_ip = body.current_ip
            changes["current_ip"] = body.current_ip
        if body.status is not None:
            node.status = body.status
            changes["status"] = body.status
        if body.region is not None:
            node.region = body.region
            changes["region"] = body.region
        session.add(
            AuditLog(
                actor_type="admin",
                actor_ref=claims.sub,
                action="admin_node_patched",
                target_type="node",
                target_id=str(node.id),
                payload=changes or None,
            )
        )
    return NodeOut(
        id=node.id,
        hostname=node.hostname,
        current_ip=node.current_ip,
        provider=node.provider,
        region=node.region,
        status=node.status,
        last_probe_at=node.last_probe_at,
        created_at=node.created_at,
    )
