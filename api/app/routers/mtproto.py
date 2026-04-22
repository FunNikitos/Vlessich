"""MTProto secret issuance (TZ §9A, updated Stage 8).

Scopes:

* ``shared`` — hand out the least-recently-created ACTIVE shared
  secret from the pool. Seeded at API startup via
  ``API_MTG_SHARED_SECRET_HEX`` (see ``app/startup/mtproto_seed.py``)
  and rotated via ``POST /admin/mtproto/rotate``.
* ``user``   — **Stage 9**. Requires mtg ``[replicas]`` orchestration
  to bind a per-user secret to a dedicated port; until then we return
  ``501 not_implemented`` so the bot surfaces a clean message instead
  of handing out a secret that mtg doesn't know about.

Gating: the requesting user must have an ACTIVE or TRIAL
subscription. Audit log records issuance with the secret row id only
(never the secret material itself).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.errors import ApiCode, api_error
from app.models import AuditLog, MtprotoSecret, Subscription, User
from app.schemas import MtprotoIn, MtprotoOut
from app.security import verify_internal_signature

router = APIRouter(
    prefix="/internal/mtproto",
    tags=["internal"],
    dependencies=[Depends(verify_internal_signature)],
)


def _deeplink(host: str, port: int, secret_hex: str, cloak: str) -> str:
    # mtg Fake-TLS secret layout: `ee` + 32 hex (secret) + hex(cloak-domain).
    cloak_hex = cloak.encode().hex()
    full = f"ee{secret_hex}{cloak_hex}"
    return f"tg://proxy?server={host}&port={port}&secret={full}"


@router.post("/issue", response_model=MtprotoOut)
async def issue(
    payload: MtprotoIn,
    session: AsyncSession = Depends(get_session),
) -> MtprotoOut:
    settings = get_settings()

    async with session.begin():
        # Require active subscription.
        sub = await session.scalar(
            select(Subscription).where(
                Subscription.user_id == payload.tg_id,
                Subscription.status.in_(("ACTIVE", "TRIAL")),
            )
        )
        if sub is None:
            raise api_error(
                status.HTTP_403_FORBIDDEN,
                ApiCode.NO_SUBSCRIPTION,
                "Нужна активная подписка.",
            )

        user = await session.scalar(select(User).where(User.tg_id == payload.tg_id))
        if user is None:
            # Shouldn't happen if subscription FK is honored, but guard anyway.
            raise api_error(
                status.HTTP_403_FORBIDDEN,
                ApiCode.NO_SUBSCRIPTION,
                "Нужна активная подписка.",
            )

        if payload.scope == "shared":
            secret = await session.scalar(
                select(MtprotoSecret)
                .where(
                    MtprotoSecret.scope == "shared",
                    MtprotoSecret.status == "ACTIVE",
                )
                .order_by(MtprotoSecret.created_at.asc())
                .limit(1)
            )
            if secret is None:
                raise api_error(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    ApiCode.NO_SHARED_POOL,
                    "Общий MTProto пул пуст. Попробуй позже.",
                )
        else:
            # Stage 8: per-user MTProto secrets require mtg [replicas]
            # orchestration (or N mtg containers on distinct ports).
            # Deferred to Stage 9; until then only the shared pool is
            # live. We still keep the scope='user' column / pick_cloak
            # helper so Stage 9 only needs to flip this branch.
            raise api_error(
                status.HTTP_501_NOT_IMPLEMENTED,
                ApiCode.NOT_IMPLEMENTED,
                "Персональный MTProto будет в следующем обновлении.",
            )

        session.add(
            AuditLog(
                actor_type="bot",
                actor_ref=str(user.tg_id),
                action="mtproto_issued",
                target_type="mtproto_secret",
                target_id=str(secret.id),
                payload={"scope": payload.scope},
            )
        )

    deeplink = _deeplink(
        settings.mtg_host, settings.mtg_port, secret.secret_hex, secret.cloak_domain
    )
    return MtprotoOut(tg_deeplink=deeplink, host=settings.mtg_host, port=settings.mtg_port)