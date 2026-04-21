"""MTProto secret issuance (TZ §9A).

Two scopes:
- ``shared``  — pull a random secret from the pool (pre-seeded via admin).
- ``user``    — mint a new 32-byte secret bound to ``user_id`` + rotating
  cloak domain, insert into ``mtproto_secrets``. Actual push to the mtg
  node happens in Stage 5 (node-side worker); here we only record state.

Gating: the requesting user must have an active or trial subscription.
Audit log records issuance with secret id (never the secret itself).
"""
from __future__ import annotations

import secrets as pysecrets

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


async def _pick_cloak(session: AsyncSession, pool: list[str]) -> str:
    if not pool:
        raise api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ApiCode.NO_SHARED_POOL,
            "MTProto cloak domain pool is empty.",
        )
    # Cheap load-balancing: pick the least-used domain within our own table.
    counts = {d: 0 for d in pool}
    rows = await session.execute(
        select(MtprotoSecret.cloak_domain, MtprotoSecret.id).where(
            MtprotoSecret.cloak_domain.in_(pool)
        )
    )
    for cloak, _ in rows.all():
        counts[cloak] = counts.get(cloak, 0) + 1
    return min(counts.items(), key=lambda kv: kv[1])[0]


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
            cloak = await _pick_cloak(session, settings.mtg_cloak_domains)
            secret = MtprotoSecret(
                secret_hex=pysecrets.token_hex(16),
                cloak_domain=cloak,
                scope="user",
                user_id=user.tg_id,
                status="ACTIVE",
            )
            session.add(secret)
            await session.flush()

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