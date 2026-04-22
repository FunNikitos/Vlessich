"""MTProto secret issuance (TZ §9A; Stage 9 FREE-pool model).

Scopes:

* ``shared`` — hand out the least-recently-created ACTIVE shared
  secret from the pool. Seeded at API startup via
  ``API_MTG_SHARED_SECRET_HEX`` (see ``app/startup/mtproto_seed.py``)
  and rotated via ``POST /admin/mtproto/rotate``.
* ``user``   — Stage 9. Per-user secrets live in a pre-seeded pool
  (status=FREE, one row per mtg port). The allocator claims the
  lowest-port FREE row (``SKIP LOCKED``) and binds it to the user.
  Gated behind ``API_MTG_PER_USER_ENABLED``: when disabled we return
  ``501 per_user_disabled`` so the bot surfaces a clean message.
  When enabled but the pool is empty we return ``503 pool_full``.

Gating: the requesting user must have an ACTIVE or TRIAL
subscription. Audit log records issuance with the secret row id +
``{scope, port}`` only — never the secret material itself.
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
from app.services.mtproto_allocator import allocate_user_secret, deeplink

router = APIRouter(
    prefix="/internal/mtproto",
    tags=["internal"],
    dependencies=[Depends(verify_internal_signature)],
)


def _deeplink(host: str, port: int, secret_hex: str, cloak: str) -> str:
    """Back-compat wrapper for tests/test_helpers.py — delegates to allocator."""
    return deeplink(host, port, secret_hex, cloak)


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
            port = settings.mtg_port
        else:
            # Stage 9: per-user via pre-seeded FREE-pool. Feature gate
            # so operator can deploy code before per-user mtg containers
            # are bootstrapped.
            if not settings.mtg_per_user_enabled:
                raise api_error(
                    status.HTTP_501_NOT_IMPLEMENTED,
                    ApiCode.PER_USER_DISABLED,
                    "Персональный MTProto выключен.",
                )
            secret = await allocate_user_secret(session, payload.tg_id)
            assert secret.port is not None  # CHECK constraint guarantees this
            port = secret.port

        session.add(
            AuditLog(
                actor_type="bot",
                actor_ref=str(user.tg_id),
                action="mtproto_issued",
                target_type="mtproto_secret",
                target_id=str(secret.id),
                payload={"scope": payload.scope, "port": port},
            )
        )

    dl = deeplink(settings.mtg_host, port, secret.secret_hex, secret.cloak_domain)
    return MtprotoOut(tg_deeplink=dl, host=settings.mtg_host, port=port)
