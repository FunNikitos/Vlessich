"""Stage 11 billing service unit tests.

Cover the ``app.services.billing`` state machine:

* ``create_order`` cleans up stale PENDING and reuses live PENDING.
* ``precheck`` validates payload + amount + state.
* ``mark_paid`` issues a fresh subscription via Remna OR extends an
  existing one; replays for the same ``telegram_payment_charge_id`` are
  idempotent; mismatched amount transitions to FAILED.
* ``refund`` revokes the subscription only when its
  ``last_order_id`` still matches the refunded order.

DB-backed; gated by ``VLESSICH_INTEGRATION_DB`` like ``test_flows_integration``.
We use the ``MockRemnawaveClient`` so no provider HTTP is exercised.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

INTEGRATION_DB = os.environ.get("VLESSICH_INTEGRATION_DB")
pytestmark = pytest.mark.skipif(
    INTEGRATION_DB is None,
    reason="set VLESSICH_INTEGRATION_DB=postgresql+asyncpg://... to run",
)

if INTEGRATION_DB:
    os.environ["API_DATABASE_URL"] = INTEGRATION_DB
os.environ.setdefault("API_INTERNAL_SECRET", "x" * 32)
os.environ.setdefault("API_SECRETBOX_KEY", "a" * 64)


@pytest.fixture
async def session():
    from app.db import get_sessionmaker, init_engine

    init_engine(INTEGRATION_DB or "")
    sm = get_sessionmaker()
    async with sm() as s:
        yield s


@pytest.fixture
async def remna():
    from app.services.remnawave import MockRemnawaveClient

    return MockRemnawaveClient()


async def _ensure_user(session, tg_id: int) -> None:
    from sqlalchemy import select

    from app.models import User

    user = await session.scalar(select(User).where(User.tg_id == tg_id))
    if user is None:
        async with session.begin():
            session.add(User(tg_id=tg_id))


async def _seed_plan(session, code: str, days: int, price: int) -> None:
    from sqlalchemy import select

    from app.models import Plan

    existing = await session.scalar(select(Plan).where(Plan.code == code))
    if existing is None:
        async with session.begin():
            session.add(
                Plan(
                    code=code,
                    duration_days=days,
                    price_xtr=price,
                    currency="XTR",
                    is_active=True,
                )
            )


async def test_create_order_inserts_pending(session, remna) -> None:
    from app.services import billing

    tg_id = 990001
    await _ensure_user(session, tg_id)
    await _seed_plan(session, "test1m", 30, 100)

    draft = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )
    assert draft.amount_xtr == 100
    assert draft.invoice_payload == str(draft.order_id)


async def test_create_order_reuses_live_pending(session, remna) -> None:
    from app.services import billing

    tg_id = 990002
    await _ensure_user(session, tg_id)
    await _seed_plan(session, "test1m", 30, 100)

    a = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )
    b = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )
    assert a.order_id == b.order_id


async def test_create_order_supersedes_stale_pending(session, remna) -> None:
    from sqlalchemy import select

    from app.models import Order
    from app.services import billing

    tg_id = 990003
    await _ensure_user(session, tg_id)
    await _seed_plan(session, "test1m", 30, 100)

    first = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )
    # Force the existing PENDING into the past so it counts as stale.
    async with session.begin():
        order = await session.scalar(
            select(Order).where(Order.id == first.order_id)
        )
        order.created_at = datetime.now(UTC) - timedelta(hours=1)

    second = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=60
    )
    assert second.order_id != first.order_id

    stale = await session.scalar(select(Order).where(Order.id == first.order_id))
    assert stale.status == "FAILED"


async def test_precheck_amount_mismatch_raises(session, remna) -> None:
    from app.services import billing

    tg_id = 990004
    await _ensure_user(session, tg_id)
    await _seed_plan(session, "test1m", 30, 100)
    draft = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )
    with pytest.raises(billing.PaymentAmountMismatch):
        await billing.precheck(
            session, invoice_payload=draft.invoice_payload, amount_xtr=101
        )


async def test_mark_paid_issues_subscription(session, remna) -> None:
    from sqlalchemy import select

    from app.models import Order, Subscription
    from app.services import billing

    tg_id = 990005
    await _ensure_user(session, tg_id)
    await _seed_plan(session, "test1m", 30, 100)
    draft = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )

    result = await billing.mark_paid(
        session,
        invoice_payload=draft.invoice_payload,
        amount_xtr=100,
        telegram_payment_charge_id="charge-1",
        provider_payment_charge_id=None,
        remna=remna,
    )
    sub = await session.scalar(
        select(Subscription).where(Subscription.id == result.subscription_id)
    )
    assert sub.status == "ACTIVE"
    assert sub.remna_user_id is not None
    assert sub.sub_url_token != ""
    assert sub.last_order_id == draft.order_id

    order = await session.scalar(select(Order).where(Order.id == draft.order_id))
    assert order.status == "PAID"
    assert order.telegram_payment_charge_id == "charge-1"


async def test_mark_paid_replay_idempotent(session, remna) -> None:
    from app.services import billing

    tg_id = 990006
    await _ensure_user(session, tg_id)
    await _seed_plan(session, "test1m", 30, 100)
    draft = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )

    a = await billing.mark_paid(
        session,
        invoice_payload=draft.invoice_payload,
        amount_xtr=100,
        telegram_payment_charge_id="charge-X",
        provider_payment_charge_id=None,
        remna=remna,
    )
    b = await billing.mark_paid(
        session,
        invoice_payload=draft.invoice_payload,
        amount_xtr=100,
        telegram_payment_charge_id="charge-X",
        provider_payment_charge_id=None,
        remna=remna,
    )
    assert a.subscription_id == b.subscription_id
    assert a.new_expires_at == b.new_expires_at


async def test_mark_paid_amount_mismatch_marks_failed(session, remna) -> None:
    from sqlalchemy import select

    from app.models import Order
    from app.services import billing

    tg_id = 990007
    await _ensure_user(session, tg_id)
    await _seed_plan(session, "test1m", 30, 100)
    draft = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )

    with pytest.raises(billing.PaymentAmountMismatch):
        await billing.mark_paid(
            session,
            invoice_payload=draft.invoice_payload,
            amount_xtr=999,
            telegram_payment_charge_id="charge-Y",
            provider_payment_charge_id=None,
            remna=remna,
        )
    order = await session.scalar(select(Order).where(Order.id == draft.order_id))
    assert order.status == "FAILED"


async def test_mark_paid_extends_existing_subscription(session, remna) -> None:
    from sqlalchemy import select

    from app.models import Subscription
    from app.services import billing

    tg_id = 990008
    await _ensure_user(session, tg_id)
    await _seed_plan(session, "test1m", 30, 100)

    d1 = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )
    r1 = await billing.mark_paid(
        session,
        invoice_payload=d1.invoice_payload,
        amount_xtr=100,
        telegram_payment_charge_id="charge-A",
        provider_payment_charge_id=None,
        remna=remna,
    )
    first_exp = r1.new_expires_at

    d2 = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )
    r2 = await billing.mark_paid(
        session,
        invoice_payload=d2.invoice_payload,
        amount_xtr=100,
        telegram_payment_charge_id="charge-B",
        provider_payment_charge_id=None,
        remna=remna,
    )
    assert r2.new_expires_at > first_exp
    sub = await session.scalar(
        select(Subscription).where(Subscription.id == r2.subscription_id)
    )
    # Same subscription row, last_order_id moved to the latest order.
    assert sub.id == r1.subscription_id
    assert sub.last_order_id == d2.order_id


async def test_refund_revokes_when_last_order_matches(session, remna) -> None:
    from sqlalchemy import select

    from app.models import Order, Subscription
    from app.services import billing

    tg_id = 990009
    await _ensure_user(session, tg_id)
    await _seed_plan(session, "test1m", 30, 100)
    draft = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )
    paid = await billing.mark_paid(
        session,
        invoice_payload=draft.invoice_payload,
        amount_xtr=100,
        telegram_payment_charge_id="charge-R1",
        provider_payment_charge_id=None,
        remna=remna,
    )

    admin_id = uuid.uuid4()
    refunded, revoked = await billing.refund(
        session, order_id=draft.order_id, admin_id=admin_id
    )
    assert refunded.status == "REFUNDED"
    assert revoked is True

    sub = await session.scalar(
        select(Subscription).where(Subscription.id == paid.subscription_id)
    )
    assert sub.status == "REVOKED"
    assert sub.last_order_id is None

    order = await session.scalar(select(Order).where(Order.id == draft.order_id))
    assert order.refunded_by_admin_id == admin_id


async def test_refund_keeps_subscription_when_superseded(session, remna) -> None:
    """First order refunded after a second order extended the sub — sub stays ACTIVE."""
    from sqlalchemy import select

    from app.models import Subscription
    from app.services import billing

    tg_id = 990010
    await _ensure_user(session, tg_id)
    await _seed_plan(session, "test1m", 30, 100)

    d1 = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )
    r1 = await billing.mark_paid(
        session,
        invoice_payload=d1.invoice_payload,
        amount_xtr=100,
        telegram_payment_charge_id="charge-S1",
        provider_payment_charge_id=None,
        remna=remna,
    )
    d2 = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )
    await billing.mark_paid(
        session,
        invoice_payload=d2.invoice_payload,
        amount_xtr=100,
        telegram_payment_charge_id="charge-S2",
        provider_payment_charge_id=None,
        remna=remna,
    )

    _, revoked = await billing.refund(
        session, order_id=d1.order_id, admin_id=uuid.uuid4()
    )
    assert revoked is False
    sub = await session.scalar(
        select(Subscription).where(Subscription.id == r1.subscription_id)
    )
    assert sub.status == "ACTIVE"
    assert sub.last_order_id == d2.order_id


async def test_refund_already_refunded_raises(session, remna) -> None:
    from app.services import billing

    tg_id = 990011
    await _ensure_user(session, tg_id)
    await _seed_plan(session, "test1m", 30, 100)
    draft = await billing.create_order(
        session, tg_id=tg_id, plan_code="test1m", pending_ttl_sec=900
    )
    await billing.mark_paid(
        session,
        invoice_payload=draft.invoice_payload,
        amount_xtr=100,
        telegram_payment_charge_id="charge-D1",
        provider_payment_charge_id=None,
        remna=remna,
    )
    await billing.refund(session, order_id=draft.order_id, admin_id=uuid.uuid4())
    with pytest.raises(billing.OrderAlreadyRefunded):
        await billing.refund(session, order_id=draft.order_id, admin_id=uuid.uuid4())


async def test_seed_default_plans_idempotent(session, remna) -> None:
    from sqlalchemy import select

    from app.models import Plan
    from app.services import billing

    inserted_first = await billing.seed_default_plans(session)
    inserted_second = await billing.seed_default_plans(session)
    assert inserted_second == 0
    # All DEFAULT_PLANS now exist.
    rows = (
        await session.scalars(
            select(Plan.code).where(Plan.code.in_(c for c, *_ in billing.DEFAULT_PLANS))
        )
    ).all()
    assert set(rows) == {c for c, *_ in billing.DEFAULT_PLANS}
    assert inserted_first >= 0  # depends on prior runs in the same DB
