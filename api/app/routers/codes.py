"""Code activation (TZ §5).

Single-transaction flow:
1. Redis rate-limit check (5/10min/tg_id by default).
2. Resolve code by sha256 hash (unique index → O(log N)).
3. Validate ciphertext equality (defense in depth against hash collision).
4. Validate window/status/reservation.
5. Lock current subscription FOR UPDATE.
6. Extend (same plan) OR replace (different plan) OR create (no sub).
7. Mark code USED, write audit_log + code_attempts, commit.

Bot consumes ``SubscriptionOut``; errors come back as ``{code, message}``.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.crypto import CipherError, get_cipher
from app.db import get_redis, get_session
from app.errors import ApiCode, api_error
from app.metrics import SUBSCRIPTION_EVENTS_TOTAL
from app.models import AuditLog, Code, CodeAttempt, Subscription, User
from app.ratelimit import check_code_rate_limit
from app.schemas import ActivateCodeIn, SubscriptionOut
from app.security import verify_internal_signature
from app.services.remnawave import RemnawaveClient, get_remnawave

router = APIRouter(
    prefix="/internal/codes",
    tags=["internal"],
    dependencies=[Depends(verify_internal_signature)],
)


def _normalize(code: str) -> str:
    return code.strip().upper().replace(" ", "")


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


async def _record_attempt(
    session: AsyncSession, *, tg_id: int, code_hash: str, result: str, ip_hash: str | None
) -> None:
    session.add(
        CodeAttempt(
            tg_id=tg_id, code_hash_attempted=code_hash, result=result, ip_hash=ip_hash
        )
    )


async def _get_or_create_user(
    session: AsyncSession, tg_id: int, referral_source: str | None
) -> User:
    user = await session.scalar(
        select(User).where(User.tg_id == tg_id).with_for_update()
    )
    if user is None:
        user = User(tg_id=tg_id, referral_source=referral_source)
        session.add(user)
        await session.flush()
    elif user.referral_source is None and referral_source is not None:
        user.referral_source = referral_source
    return user


@router.post("/activate", response_model=SubscriptionOut)
async def activate(
    payload: ActivateCodeIn,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    remna: RemnawaveClient = Depends(get_remnawave),
) -> SubscriptionOut:
    settings = get_settings()
    normalized = _normalize(payload.code)
    code_hash = _hash(normalized)

    # 1. Rate limit (outside transaction; failure must NOT touch DB).
    allowed = await check_code_rate_limit(
        redis,
        payload.tg_id,
        limit=settings.code_rl_attempts,
        window_sec=settings.code_rl_window_sec,
    )
    if not allowed:
        async with session.begin():
            await _record_attempt(
                session,
                tg_id=payload.tg_id,
                code_hash=code_hash,
                result="rl",
                ip_hash=payload.ip_hash,
            )
        raise api_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            ApiCode.RATE_LIMITED,
            "Слишком много попыток. Подожди 10 минут.",
        )

    cipher = get_cipher()
    now = datetime.now(UTC)

    async with session.begin():
        # 2. Lookup by hash, lock FOR UPDATE.
        code = await session.scalar(
            select(Code).where(Code.code_hash == code_hash).with_for_update()
        )
        if code is None:
            await _record_attempt(
                session,
                tg_id=payload.tg_id,
                code_hash=code_hash,
                result="bad",
                ip_hash=payload.ip_hash,
            )
            raise api_error(
                status.HTTP_404_NOT_FOUND, ApiCode.CODE_NOT_FOUND, "Код не найден."
            )

        # 3. Defense in depth: ciphertext must match plaintext.
        try:
            plaintext = cipher.open(code.code_enc)
        except CipherError as exc:
            raise api_error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                ApiCode.INTERNAL,
                "Ошибка расшифровки кода.",
            ) from exc
        if plaintext != normalized:
            await _record_attempt(
                session,
                tg_id=payload.tg_id,
                code_hash=code_hash,
                result="bad",
                ip_hash=payload.ip_hash,
            )
            raise api_error(
                status.HTTP_404_NOT_FOUND, ApiCode.CODE_NOT_FOUND, "Код не найден."
            )

        # 4. Status / window / reservation.
        if code.status != "ACTIVE":
            result = "used" if code.status == "USED" else "expired"
            await _record_attempt(
                session,
                tg_id=payload.tg_id,
                code_hash=code_hash,
                result=result,
                ip_hash=payload.ip_hash,
            )
            err_code = ApiCode.CODE_USED if code.status == "USED" else ApiCode.CODE_EXPIRED
            raise api_error(status.HTTP_409_CONFLICT, err_code, "Код недоступен.")

        if not (code.valid_from <= now <= code.valid_until):
            await _record_attempt(
                session,
                tg_id=payload.tg_id,
                code_hash=code_hash,
                result="expired",
                ip_hash=payload.ip_hash,
            )
            raise api_error(
                status.HTTP_409_CONFLICT, ApiCode.CODE_EXPIRED, "Код просрочен."
            )

        if code.reserved_for_tg_id is not None and code.reserved_for_tg_id != payload.tg_id:
            await _record_attempt(
                session,
                tg_id=payload.tg_id,
                code_hash=code_hash,
                result="reserved",
                ip_hash=payload.ip_hash,
            )
            raise api_error(
                status.HTTP_403_FORBIDDEN,
                ApiCode.CODE_RESERVED,
                "Код предназначен другому пользователю.",
            )

        # 5. Resolve user + current subscription.
        user = await _get_or_create_user(session, payload.tg_id, payload.referral_source)
        active = await session.scalar(
            select(Subscription)
            .where(
                Subscription.user_id == user.tg_id,
                Subscription.status.in_(("ACTIVE", "TRIAL")),
            )
            .with_for_update()
        )

        # 6. Extend / replace / create.
        if active is None:
            sub = Subscription(
                user_id=user.tg_id,
                code_id=code.id,
                plan=code.plan_name,
                started_at=now,
                expires_at=now + timedelta(days=code.duration_days),
                devices_limit=code.devices_limit,
                traffic_limit_gb=code.traffic_limit_gb,
                adblock=code.adblock_default,
                smart_routing=code.smart_routing_default,
                status="ACTIVE",
                sub_url_token="pending",
            )
            session.add(sub)
            await session.flush()
            remna_user = await remna.create_user(sub.id, code.plan_name, code.duration_days)
            sub.sub_url_token = remna_user.sub_token
            sub.remna_user_id = remna_user.remna_user_id
            audit_action = "subscription_created"

        elif active.plan == code.plan_name:
            base = max(active.expires_at or now, now)
            active.expires_at = base + timedelta(days=code.duration_days)
            active.status = "ACTIVE"
            if active.remna_user_id is not None:
                await remna.extend_user(active.remna_user_id, code.duration_days)
            sub = active
            audit_action = "subscription_extended"

        else:
            # Replace: revoke old (Remna + DB), create new.
            if active.remna_user_id is not None:
                await remna.revoke_user(active.remna_user_id)
            active.status = "REVOKED"
            await session.flush()
            sub = Subscription(
                user_id=user.tg_id,
                code_id=code.id,
                plan=code.plan_name,
                started_at=now,
                expires_at=now + timedelta(days=code.duration_days),
                devices_limit=code.devices_limit,
                traffic_limit_gb=code.traffic_limit_gb,
                adblock=code.adblock_default,
                smart_routing=code.smart_routing_default,
                status="ACTIVE",
                sub_url_token="pending",
            )
            session.add(sub)
            await session.flush()
            remna_user = await remna.create_user(sub.id, code.plan_name, code.duration_days)
            sub.sub_url_token = remna_user.sub_token
            sub.remna_user_id = remna_user.remna_user_id
            audit_action = "subscription_replaced"

        # 7. Mark code, audit, attempt.
        if code.single_use:
            code.status = "USED"
        code.activated_by_user = user.tg_id
        code.activated_at = now

        session.add(
            AuditLog(
                actor_type="bot",
                actor_ref=str(user.tg_id),
                action=audit_action,
                target_type="subscription",
                target_id=str(sub.id),
                payload={
                    "code_id": str(code.id),
                    "plan": code.plan_name,
                    "duration_days": code.duration_days,
                },
            )
        )
        await _record_attempt(
            session,
            tg_id=payload.tg_id,
            code_hash=code_hash,
            result="ok",
            ip_hash=payload.ip_hash,
        )

    if audit_action == "subscription_created":
        SUBSCRIPTION_EVENTS_TOTAL.labels(event="issued").inc()
    elif audit_action == "subscription_replaced":
        SUBSCRIPTION_EVENTS_TOTAL.labels(event="issued").inc()
        SUBSCRIPTION_EVENTS_TOTAL.labels(event="revoked").inc()

    return SubscriptionOut(
        status="ACTIVE",
        plan=sub.plan,
        expires_at=sub.expires_at,
        sub_token=sub.sub_url_token,
        devices_limit=sub.devices_limit,
        traffic_limit_gb=sub.traffic_limit_gb,
    )