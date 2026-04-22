"""Smoke tests for Stage 11 purchase handler wiring (no Telegram I/O)."""
from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("BOT_API_BASE_URL", "http://api:8000")
os.environ.setdefault("BOT_API_INTERNAL_SECRET", "x" * 32)

from app.handlers import purchase
from app.texts import (
    BUY_DISABLED,
    BUY_INVOICE_DESCRIPTION,
    BUY_INVOICE_TITLE,
    BUY_PLAN_BUTTON,
    BUY_PLAN_LABEL,
    BUY_PROMPT,
    PAYMENT_FAILED,
    PAYMENT_SUCCESS,
    REFUND_NOTICE,
)


def test_router_name_and_handlers_registered() -> None:
    assert purchase.router.name == "purchase"
    # Sanity: each handler module-level callable still exists & is async.
    import inspect

    for fn in (
        purchase.buy_cmd,
        purchase.buy_callback,
        purchase.buy_plan,
        purchase.on_pre_checkout,
        purchase.on_successful_payment,
    ):
        assert inspect.iscoroutinefunction(fn)


def test_plans_kb_renders_one_row_per_plan() -> None:
    from app.services.api_client import PlanInfo

    plans = [
        PlanInfo(code="1m", duration_days=30, price_xtr=100, currency="XTR"),
        PlanInfo(code="3m", duration_days=90, price_xtr=250, currency="XTR"),
        PlanInfo(code="12m", duration_days=365, price_xtr=900, currency="XTR"),
    ]
    kb = purchase._plans_kb(plans)
    assert len(kb.inline_keyboard) == 3
    for row, plan in zip(kb.inline_keyboard, plans, strict=True):
        assert len(row) == 1
        btn = row[0]
        assert btn.callback_data == f"buy:plan:{plan.code}"
        # Label formatting carries the human plan label + price.
        assert str(plan.price_xtr) in btn.text
        assert BUY_PLAN_LABEL[plan.code] in btn.text


def test_plan_label_falls_back_to_code() -> None:
    from app.services.api_client import PlanInfo

    plan = PlanInfo(code="999y", duration_days=1, price_xtr=1, currency="XTR")
    assert purchase._plan_label(plan) == "999y"


def test_text_invariants_present() -> None:
    # Format placeholders are documented; ensure the strings stayed compatible.
    assert "{label}" in BUY_INVOICE_TITLE
    assert "{label}" in BUY_INVOICE_DESCRIPTION
    assert "{label}" in BUY_PLAN_BUTTON and "{price}" in BUY_PLAN_BUTTON
    assert "{expires_at}" in PAYMENT_SUCCESS
    # Disabled / failure notices are non-empty so users always see something.
    assert BUY_DISABLED.strip()
    assert BUY_PROMPT.strip()
    assert PAYMENT_FAILED.strip()
    assert REFUND_NOTICE.strip()
