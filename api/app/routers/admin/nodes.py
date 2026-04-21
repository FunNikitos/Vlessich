"""Admin nodes management (Stage 2 T7).

Read open to all roles; create/patch restricted to ``superadmin``.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import AdminClaims, require_admin_role
from app.db import get_session
from app.errors import ApiCode, api_error
from app.models import AuditLog, Node, NodeHealthProbe
from app.schemas import HealthProbeOut, NodeHealthOut

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


# ---------------------------------------------------------------------------
# Manual rotation acknowledgement (Stage 5 T4)
# ---------------------------------------------------------------------------
@router.post("/{node_id}/rotate", response_model=NodeOut)
async def rotate_node(
    node_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    claims: Annotated[AdminClaims, Depends(require_admin_role("superadmin"))],
) -> NodeOut:
    """Acknowledge external IP rotation — clear ``current_ip``, set HEALTHY.

    Use after the operator has rotated the upstream IP at the hosting
    provider. The next prober tick will populate fresh probe data.
    """
    async with session.begin():
        node = await session.scalar(
            select(Node).where(Node.id == node_id).with_for_update()
        )
        if node is None:
            raise api_error(
                status.HTTP_404_NOT_FOUND, ApiCode.NODE_NOT_FOUND, "node not found"
            )
        previous_ip = node.current_ip
        previous_status = node.status
        node.current_ip = None
        node.status = "HEALTHY"
        session.add(
            AuditLog(
                actor_type="admin",
                actor_ref=claims.sub,
                action="node_rotated",
                target_type="node",
                target_id=str(node.id),
                payload={
                    "hostname": node.hostname,
                    "previous_ip": previous_ip,
                    "previous_status": previous_status,
                },
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


# ---------------------------------------------------------------------------
# Health snapshot (Stage 4 T1)
# ---------------------------------------------------------------------------
@router.get("/{node_id}/health", response_model=NodeHealthOut)
async def node_health(
    node_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _claims: Annotated[AdminClaims, Depends(require_admin_role(*_READ_ROLES))],
) -> NodeHealthOut:
    node = await session.scalar(select(Node).where(Node.id == node_id))
    if node is None:
        raise api_error(
            status.HTTP_404_NOT_FOUND, ApiCode.NODE_NOT_FOUND, "node not found"
        )

    recent_rows = (
        await session.execute(
            select(NodeHealthProbe)
            .where(NodeHealthProbe.node_id == node_id)
            .order_by(NodeHealthProbe.probed_at.desc())
            .limit(50)
        )
    ).scalars().all()
    recent = [
        HealthProbeOut(
            probed_at=p.probed_at,
            ok=p.ok,
            latency_ms=p.latency_ms,
            error=p.error,
        )
        for p in recent_rows
    ]

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    total_24h = (
        await session.scalar(
            select(func.count())
            .select_from(NodeHealthProbe)
            .where(
                NodeHealthProbe.node_id == node_id,
                NodeHealthProbe.probed_at >= cutoff,
            )
        )
        or 0
    )
    ok_24h = (
        await session.scalar(
            select(func.count())
            .select_from(NodeHealthProbe)
            .where(
                NodeHealthProbe.node_id == node_id,
                NodeHealthProbe.probed_at >= cutoff,
                NodeHealthProbe.ok.is_(True),
            )
        )
        or 0
    )
    uptime_pct: float | None = None
    if total_24h > 0:
        uptime_pct = round(float(ok_24h) / float(total_24h) * 100.0, 2)

    p50 = await session.scalar(
        select(
            func.percentile_cont(0.5).within_group(
                NodeHealthProbe.latency_ms.asc()
            )
        ).where(
            NodeHealthProbe.node_id == node_id,
            NodeHealthProbe.probed_at >= cutoff,
            NodeHealthProbe.ok.is_(True),
            NodeHealthProbe.latency_ms.is_not(None),
        )
    )
    p95 = await session.scalar(
        select(
            func.percentile_cont(0.95).within_group(
                NodeHealthProbe.latency_ms.asc()
            )
        ).where(
            NodeHealthProbe.node_id == node_id,
            NodeHealthProbe.probed_at >= cutoff,
            NodeHealthProbe.ok.is_(True),
            NodeHealthProbe.latency_ms.is_not(None),
        )
    )

    return NodeHealthOut(
        node_id=str(node.id),
        hostname=node.hostname,
        status=node.status,
        current_ip=node.current_ip,
        region=node.region,
        last_probe_at=node.last_probe_at,
        uptime_24h_pct=uptime_pct,
        latency_p50_ms=float(p50) if p50 is not None else None,
        latency_p95_ms=float(p95) if p95 is not None else None,
        recent_probes=recent,
    )
