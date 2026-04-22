"""Subscription inbound payload composer (Stage 2 T2).

Builds a normalized JSON payload ``{inbounds: [...], meta: {...}}`` for a
given subscription. The sub-Worker at Cloudflare edge converts this into
concrete client formats (Clash, sing-box, Surge, v2ray, raw).

The composer never logs decrypted UUIDs or passwords. Callers must not
include the return value in structured logs either.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import CipherError, get_cipher
from app.models import Device, Node, Subscription

InboundProto = Literal["vless-reality-vision", "vless-reality-xhttp", "hysteria2"]


@dataclass(frozen=True, slots=True)
class InboundNode:
    """Wire-level inbound descriptor (no secrets in log output).

    ``remarks`` is user-facing; secrets (``uuid``/``password``) are consumed
    by the Worker and serialized into the chosen client format.
    """

    protocol: InboundProto
    host: str
    port: int
    remarks: str
    sni: str | None = None
    public_key: str | None = None
    short_id: str | None = None
    flow: str | None = None
    path: str | None = None
    uuid: str | None = None
    password: str | None = None
    alpn: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PayloadMeta:
    status: str
    plan: str
    expires_at: datetime | None
    devices_limit: int


class PayloadError(RuntimeError):
    """Unrecoverable composer failure (decryption, missing node, etc.)."""


async def build_payload(session: AsyncSession, subscription_id: UUID) -> dict[str, object]:
    """Load subscription + devices + node and materialize inbounds[].

    Raises ``PayloadError`` if the subscription has no healthy node assigned
    or if device UUID decryption fails (indicates key rotation or tamper).
    """
    sub = (
        await session.execute(
            select(Subscription).where(Subscription.id == subscription_id)
        )
    ).scalar_one_or_none()
    if sub is None:
        raise PayloadError("subscription not found")

    devices = (
        await session.execute(
            select(Device).where(Device.subscription_id == subscription_id)
        )
    ).scalars().all()

    node: Node | None = None
    if sub.current_node_id is not None:
        node = (
            await session.execute(select(Node).where(Node.id == sub.current_node_id))
        ).scalar_one_or_none()

    cipher = get_cipher()
    inbounds: list[InboundNode] = []
    if node is not None and node.status == "HEALTHY":
        for idx, dev in enumerate(devices):
            try:
                uuid_plain = cipher.open(dev.xray_uuid_enc)
            except CipherError as exc:
                raise PayloadError(
                    f"device {dev.id} uuid decryption failed"
                ) from exc
            remarks_prefix = f"vlessich-{node.region or 'fi'}-{idx + 1}"
            inbounds.append(
                InboundNode(
                    protocol="vless-reality-vision",
                    host=node.current_ip or node.hostname,
                    port=443,
                    sni="www.cloudflare.com",
                    public_key=_reality_pubkey_placeholder(),
                    short_id=_reality_short_id(dev.id.hex),
                    flow="xtls-rprx-vision",
                    uuid=uuid_plain,
                    remarks=f"{remarks_prefix}-vision",
                )
            )
            inbounds.append(
                InboundNode(
                    protocol="vless-reality-xhttp",
                    host=node.current_ip or node.hostname,
                    port=443,
                    sni="www.cloudflare.com",
                    public_key=_reality_pubkey_placeholder(),
                    short_id=_reality_short_id(dev.id.hex),
                    path="/xhttp",
                    uuid=uuid_plain,
                    alpn=["h3", "h2"],
                    remarks=f"{remarks_prefix}-xhttp",
                )
            )

    meta = PayloadMeta(
        status=sub.status,
        plan=sub.plan,
        expires_at=sub.expires_at,
        devices_limit=sub.devices_limit,
    )
    return {
        "inbounds": [asdict(i) for i in inbounds],
        "meta": {
            "status": meta.status,
            "plan": meta.plan,
            "expires_at": meta.expires_at.isoformat() if meta.expires_at else None,
            "devices_limit": meta.devices_limit,
        },
    }


def _reality_pubkey_placeholder() -> str:
    """Reality public key is stored per-node in Stage 5; placeholder for now.

    Returning empty string is safe: the Worker treats missing pubkey as
    "not configured" and skips the inbound. Stage 5 will wire node.pubkey.
    """
    return ""


def _reality_short_id(seed_hex: str) -> str:
    """Deterministic 8-hex short_id from a 32-hex seed (device UUID bytes)."""
    return seed_hex[:8]


__all__ = ["InboundNode", "PayloadMeta", "PayloadError", "build_payload"]
