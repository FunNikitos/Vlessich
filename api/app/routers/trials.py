"""Trials issuance (TZ §4.1).

One trial per ``tg_id`` AND per fingerprint (``sha256(phone+tg_id+fp_salt)``).
Single transaction guarantees:
- create or update user (capturing referral_source on first contact)
- check trial uniqueness with row-level lock
- provision Remna user via injected client
- insert subscription (status=TRIAL) — partial unique index enforces 1 active
  subscription per user
- write audit_log

Errors are raised via ``api_error()`` so bot sees ``{code, message}``.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errors import ApiCode, api_error
from app.db import get_session
from app.models import AuditLog, Subscription, Trial, User
from app.schemas import SubscriptionOut, TrialIn
from app.security import verify_internal_signature
from app.services.remnawave import RemnawaveClient, get_remnawave

router = APIRouter(
    prefix="/internal/trials",
    tags=["internal"],
    dependencies=[Depends(verify_internal_signature)],
)


def _fingerprint(phone_e164: str, tg_id: int, salt: str) -> str:
    return hashlib.sha256(f"{phone_e164}|{tg_id}|{salt}".encode()).hexdigest()


async def _get_or_create_user(
    session: AsyncSession,
    tg_id: int,
    phone_e164: str,
    fingerprint_hash: str,
    referral_source: str | None,
) -> User:
    user = await session.scalar(
        select(User).where(User.tg_id == tg_id).with_for_update()
    )
    if user is None:
        user = User(
            tg_id=tg_id,
            phone_e164=phone_e164,
            fingerprint_hash=fingerprint_hash,
            referral_source=referral_source,
        )
        session.add(user)
        await session.flush()
        return user
    if user.phone_e164 is None:
        user.phone_e164 = phone_e164
    if user.fingerprint_hash is None:
        user.fingerprint_hash = fingerprint_hash
    if user.referral_source is None and referral_source is not None:
        user.referral_source = referral_source
    return user


@router.post("", response_model=SubscriptionOut)
async def create_trial(
    payload: TrialIn,
    session: AsyncSession = Depends(get_session),
    remna: RemnawaveClient = Depends(get_remnawave),
) -> SubscriptionOut:
    settings = get_settings()
    fp = _fingerprint(payload.phone_e164, payload.tg_id, settings.fp_salt.get_secret_value())

    async with session.begin():
        # Reject by fingerprint OR tg_id collision (both unique constraints
        # exist in DB, but we want the *correct* error code in the response).
        existing = await session.scalar(
            select(Trial).where(
                (Trial.tg_id == payload.tg_id) | (Trial.fingerprint_hash == fp)
            )
        )
        if existing is not None:
            raise api_error(
                status.HTTP_409_CONFLICT,
                ApiCode.TRIAL_ALREADY_USED,
                "Триал уже использован.",
            )

        user = await _get_or_create_user(
            session, payload.tg_id, payload.phone_e164, fp, payload.referral_source
        )

        # Reject if user already has an active/trial subscription (rare race).
        active = await session.scalar(
            select(Subscription).where(
                Subscription.user_id == user.tg_id,
                Subscription.status.in_(("ACTIVE", "TRIAL")),
            )
        )
        if active is not None:
            raise api_error(
                status.HTTP_409_CONFLICT,
                ApiCode.TRIAL_ALREADY_USED,
                "У вас уже есть активная подписка.",
            )

        ttl_days = settings.trial_days
        sub = Subscription(
            user_id=user.tg_id,
            plan="trial",
            started_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
            devices_limit=1,
            adblock=True,
            smart_routing=True,
            status="TRIAL",
            sub_url_token="pending",  # replaced below
        )
        session.add(sub)
        await session.flush()  # populates sub.id

        remna_user = await remna.create_user(sub.id, "trial", ttl_days)
        sub.sub_url_token = remna_user.sub_token
        sub.remna_user_id = remna_user.remna_user_id

        session.add(
            Trial(
                tg_id=user.tg_id,
                fingerprint_hash=fp,
                subscription_id=sub.id,
                ip_hash=payload.ip_hash,
            )
        )
        session.add(
            AuditLog(
                actor_type="bot",
                actor_ref=str(user.tg_id),
                action="trial_issued",
                target_type="subscription",
                target_id=str(sub.id),
                payload={"referral_source": payload.referral_source},
            )
        )

    return SubscriptionOut(
        status="TRIAL",
        plan=sub.plan,
        expires_at=sub.expires_at,
        sub_token=sub.sub_url_token,
        devices_limit=sub.devices_limit,
    )