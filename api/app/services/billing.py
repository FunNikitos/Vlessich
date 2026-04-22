"""Billing service — Telegram Stars MVP (Stage 11).

Pure async functions over ``AsyncSession`` and ``Settings``. Routers
adapt errors to ``api_error(...)``; this module raises typed
``BillingError`` subclasses so it stays HTTP-agnostic and unit-testable
without FastAPI.

State machine (orders):

    (none) ── create_order ──▶ PENDING
                              ├── precheck(ok)  ──▶ PENDING (no-op)
                              ├── precheck(no)  ──▶ FAILED
                              └── mark_paid     ──▶ PAID ──▶ refund ──▶ REFUNDED

``mark_paid`` is responsible for extending or issuing the user's
``Subscription`` and stamping ``Subscription.last_order_id``. Refund
revokes the subscription **only** when its ``last_order_id`` matches
the refunded order (i.e. that order paid for the current expiry).

Currency is locked to ``XTR`` for MVP. ``currency`` columns exist on
``plans`` / ``orders`` for forward-compat with future providers.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ApiCode
from app.metrics import ORDERS_TOTAL, REFUNDS_TOTAL, REVENUE_XTR_TOTAL
from app.models import AuditLog, Order, Plan, Subscription

log = structlog.get_logger("billing")

# ---------------------------------------------------------------------------
# Default plan catalog (idempotent seed). Prices are placeholders; real
# tuning lives in a data-only migration or an admin tool. Seed inserts
# rows ONLY if absent — never updates an existing row, so manual price
# adjustments survive restarts.
# ---------------------------------------------------------------------------
DEFAULT_PLANS: Final[tuple[tuple[str, int, int], ...]] = (
    ("1m", 30, 100),
    ("3m", 90, 250),
    ("12m", 365, 900),
)


# ---------------------------------------------------------------------------
# Typed errors (router maps these to ApiCode + HTTP status).
# ---------------------------------------------------------------------------
class BillingError(Exception):
    code: ApiCode = ApiCode.INTERNAL


class BillingDisabled(BillingError):
    code = ApiCode.BILLING_DISABLED


class InvalidPlan(BillingError):
    code = ApiCode.INVALID_PLAN


class OrderNotFound(BillingError):
    code = ApiCode.ORDER_NOT_FOUND


class OrderNotPending(BillingError):
    code = ApiCode.ORDER_NOT_PENDING


class OrderNotPaid(BillingError):
    code = ApiCode.ORDER_NOT_PAID


class OrderAlreadyRefunded(BillingError):
    code = ApiCode.ORDER_ALREADY_REFUNDED


class PaymentAmountMismatch(BillingError):
    code = ApiCode.PAYMENT_AMOUNT_MISMATCH


# ---------------------------------------------------------------------------
# DTOs (router-facing). Pydantic stays in routers; this module returns
# plain dataclasses so it remains framework-agnostic.
# ---------------------------------------------------------------------------
@dataclass(slots=True, frozen=True)
class PlanView:
    code: str
    duration_days: int
    price_xtr: int
    currency: str


@dataclass(slots=True, frozen=True)
class OrderDraft:
    order_id: uuid.UUID
    invoice_payload: str
    amount_xtr: int
    currency: str
    plan_code: str
    duration_days: int


@dataclass(slots=True, frozen=True)
class PaidResult:
    order_id: uuid.UUID
    subscription_id: uuid.UUID
    new_expires_at: datetime


@dataclass(slots=True, frozen=True)
class RefundResult:
    order_id: uuid.UUID
    subscription_revoked: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _load_plan(session: AsyncSession, code: str) -> Plan:
    plan = await session.scalar(
        select(Plan).where(Plan.code == code, Plan.is_active.is_(True))
    )
    if plan is None:
        raise InvalidPlan(code)
    return plan


async def _load_order_for_update(
    session: AsyncSession, order_id: uuid.UUID
) -> Order:
    order = await session.scalar(
        select(Order).where(Order.id == order_id).with_for_update()
    )
    if order is None:
        raise OrderNotFound(str(order_id))
    return order


def _parse_payload(invoice_payload: str) -> uuid.UUID:
    try:
        return uuid.UUID(invoice_payload)
    except (ValueError, AttributeError) as exc:
        raise OrderNotFound(invoice_payload) from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def list_active_plans(session: AsyncSession) -> list[PlanView]:
    rows = (
        await session.scalars(
            select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.duration_days)
        )
    ).all()
    return [
        PlanView(
            code=p.code,
            duration_days=p.duration_days,
            price_xtr=p.price_xtr,
            currency=p.currency,
        )
        for p in rows
    ]


async def create_order(
    session: AsyncSession,
    *,
    tg_id: int,
    plan_code: str,
    pending_ttl_sec: int,
) -> OrderDraft:
    """Create a fresh PENDING order, cleaning up any stale prior PENDING.

    Stale = ``status='PENDING' AND created_at < now - pending_ttl_sec``.
    The partial unique ``ix_orders_one_pending_per_user`` enforces a
    single live PENDING per user; we mark the old one FAILED before
    inserting the new one.
    """
    async with session.begin():
        plan = await _load_plan(session, plan_code)
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=pending_ttl_sec)

        existing = await session.scalar(
            select(Order)
            .where(Order.user_id == tg_id, Order.status == "PENDING")
            .with_for_update()
        )
        if existing is not None:
            if existing.created_at <= cutoff:
                existing.status = "FAILED"
                await session.flush()
            else:
                # Reuse live draft so user can pay for it.
                return OrderDraft(
                    order_id=existing.id,
                    invoice_payload=existing.invoice_payload,
                    amount_xtr=existing.amount_xtr,
                    currency=existing.currency,
                    plan_code=existing.plan_code,
                    duration_days=plan.duration_days,
                )

        order_id = uuid.uuid4()
        order = Order(
            id=order_id,
            user_id=tg_id,
            plan_code=plan.code,
            amount_xtr=plan.price_xtr,
            currency=plan.currency,
            status="PENDING",
            invoice_payload=str(order_id),
        )
        session.add(order)
        session.add(
            AuditLog(
                actor_type="user",
                actor_ref=str(tg_id),
                action="order_created",
                target_type="order",
                target_id=str(order_id),
                payload={
                    "plan_code": plan.code,
                    "amount_xtr": plan.price_xtr,
                    "currency": plan.currency,
                },
            )
        )

    log.info(
        "billing.order.created",
        order_id=str(order_id),
        tg_id=tg_id,
        plan_code=plan.code,
        amount_xtr=plan.price_xtr,
    )
    ORDERS_TOTAL.labels(status="created", plan=plan.code).inc()
    return OrderDraft(
        order_id=order_id,
        invoice_payload=str(order_id),
        amount_xtr=plan.price_xtr,
        currency=plan.currency,
        plan_code=plan.code,
        duration_days=plan.duration_days,
    )


async def precheck(
    session: AsyncSession, *, invoice_payload: str, amount_xtr: int
) -> Order:
    """Validate a Telegram pre_checkout_query.

    Caller (bot) MUST answer ``ok=False`` on any exception. We do NOT
    transition to FAILED here — Telegram retries pre_checkout for the
    same invoice, and the user might fix client-side issues. FAILED is
    emitted only by ``mark_paid`` when amount mismatches, or by
    ``create_order`` when cleaning a stale PENDING.
    """
    order_id = _parse_payload(invoice_payload)
    order = await session.scalar(select(Order).where(Order.id == order_id))
    if order is None:
        raise OrderNotFound(invoice_payload)
    if order.status != "PENDING":
        raise OrderNotPending(str(order_id))
    if order.amount_xtr != amount_xtr:
        raise PaymentAmountMismatch(
            f"order={order.amount_xtr} got={amount_xtr}"
        )
    return order


def _extend_subscription(
    sub: Subscription, *, duration_days: int, now: datetime, order_id: uuid.UUID
) -> datetime:
    """In-place extension. Returns new ``expires_at``."""
    base = max(sub.expires_at or now, now) if sub.status in ("ACTIVE", "TRIAL") else now
    sub.expires_at = base + timedelta(days=duration_days)
    sub.status = "ACTIVE"
    sub.last_order_id = order_id
    return sub.expires_at


async def mark_paid(
    session: AsyncSession,
    *,
    invoice_payload: str,
    amount_xtr: int,
    telegram_payment_charge_id: str,
    provider_payment_charge_id: str | None,
) -> PaidResult:
    """Idempotently transition PENDING → PAID and extend/issue subscription.

    Idempotency: if the order is already PAID with the same
    ``telegram_payment_charge_id``, return the existing state without
    double-charging. If charge ids mismatch, raise ``OrderNotPending``.
    """
    order_id = _parse_payload(invoice_payload)

    async with session.begin():
        order = await _load_order_for_update(session, order_id)

        if order.status == "PAID":
            if order.telegram_payment_charge_id == telegram_payment_charge_id:
                # Replay — surface current state.
                sub = await session.scalar(
                    select(Subscription).where(
                        Subscription.last_order_id == order.id
                    )
                )
                if sub is None or sub.expires_at is None:
                    raise OrderNotPending(str(order_id))
                return PaidResult(
                    order_id=order.id,
                    subscription_id=sub.id,
                    new_expires_at=sub.expires_at,
                )
            raise OrderNotPending(str(order_id))

        if order.status != "PENDING":
            raise OrderNotPending(str(order_id))

        if order.amount_xtr != amount_xtr:
            order.status = "FAILED"
            raise PaymentAmountMismatch(
                f"order={order.amount_xtr} got={amount_xtr}"
            )

        plan = await _load_plan(session, order.plan_code)
        now = datetime.now(UTC)

        # Lock current subscription (if any) for the user.
        sub = await session.scalar(
            select(Subscription)
            .where(
                Subscription.user_id == order.user_id,
                Subscription.status.in_(("ACTIVE", "TRIAL", "EXPIRED")),
            )
            .order_by(Subscription.started_at.desc())
            .with_for_update()
        )

        if sub is None:
            sub = Subscription(
                user_id=order.user_id,
                plan=plan.code,
                started_at=now,
                expires_at=now + timedelta(days=plan.duration_days),
                devices_limit=1,
                adblock=True,
                smart_routing=True,
                status="ACTIVE",
                sub_url_token=f"pending-{order.id.hex}",
                last_order_id=order.id,
            )
            session.add(sub)
            await session.flush()
        else:
            _extend_subscription(
                sub,
                duration_days=plan.duration_days,
                now=now,
                order_id=order.id,
            )

        order.status = "PAID"
        order.paid_at = now
        order.telegram_payment_charge_id = telegram_payment_charge_id
        order.provider_payment_charge_id = provider_payment_charge_id

        session.add(
            AuditLog(
                actor_type="user",
                actor_ref=str(order.user_id),
                action="order_paid",
                target_type="order",
                target_id=str(order.id),
                payload={
                    "plan_code": plan.code,
                    "amount_xtr": amount_xtr,
                    "subscription_id": str(sub.id),
                },
            )
        )

    log.info(
        "billing.order.paid",
        order_id=str(order.id),
        tg_id=order.user_id,
        plan_code=plan.code,
        amount_xtr=amount_xtr,
    )
    ORDERS_TOTAL.labels(status="paid", plan=plan.code).inc()
    REVENUE_XTR_TOTAL.labels(plan=plan.code).inc(amount_xtr)
    assert sub.expires_at is not None  # set just above
    return PaidResult(
        order_id=order.id,
        subscription_id=sub.id,
        new_expires_at=sub.expires_at,
    )


async def refund(
    session: AsyncSession,
    *,
    order_id: uuid.UUID,
    admin_id: uuid.UUID,
) -> tuple[Order, bool]:
    """Pre-flight checks + state transition for refund.

    Returns ``(order, subscription_was_revoked)``. Caller (admin
    router) executes the actual ``bot.refund_star_payment(...)`` HTTP
    push BEFORE invoking this; we transition to REFUNDED only on
    successful upstream refund.

    If the order is the most recent payment for an ACTIVE subscription
    (``Subscription.last_order_id == order.id``), the subscription is
    REVOKED. Otherwise (subsequent paid order extended further), we
    leave the subscription untouched — the refund is for an earlier
    overlap that has already been superseded.
    """
    async with session.begin():
        order = await _load_order_for_update(session, order_id)

        if order.status == "REFUNDED":
            raise OrderAlreadyRefunded(str(order_id))
        if order.status != "PAID":
            raise OrderNotPaid(str(order_id))

        sub = await session.scalar(
            select(Subscription)
            .where(Subscription.last_order_id == order.id)
            .with_for_update()
        )
        revoked = False
        if sub is not None and sub.status in ("ACTIVE", "TRIAL"):
            sub.status = "REVOKED"
            sub.last_order_id = None
            revoked = True

        order.status = "REFUNDED"
        order.refunded_at = datetime.now(UTC)
        order.refunded_by_admin_id = admin_id

        session.add(
            AuditLog(
                actor_type="admin",
                actor_ref=str(admin_id),
                action="order_refunded",
                target_type="order",
                target_id=str(order.id),
                payload={
                    "plan_code": order.plan_code,
                    "amount_xtr": order.amount_xtr,
                    "subscription_revoked": revoked,
                },
            )
        )

    log.info(
        "billing.order.refunded",
        order_id=str(order.id),
        tg_id=order.user_id,
        subscription_revoked=revoked,
    )
    ORDERS_TOTAL.labels(status="refunded", plan=order.plan_code).inc()
    REFUNDS_TOTAL.labels(plan=order.plan_code).inc()
    return order, revoked


# ---------------------------------------------------------------------------
# Startup seed (idempotent, no UPDATE).
# ---------------------------------------------------------------------------
async def seed_default_plans(session: AsyncSession) -> int:
    """Insert ``DEFAULT_PLANS`` rows that don't yet exist. Returns count inserted."""
    inserted = 0
    async with session.begin():
        existing_codes = set(
            (await session.scalars(select(Plan.code))).all()
        )
        for code, duration_days, price_xtr in DEFAULT_PLANS:
            if code in existing_codes:
                continue
            session.add(
                Plan(
                    code=code,
                    duration_days=duration_days,
                    price_xtr=price_xtr,
                    currency="XTR",
                    is_active=True,
                )
            )
            inserted += 1
    if inserted:
        log.info("billing.plans.seeded", count=inserted)
    return inserted
