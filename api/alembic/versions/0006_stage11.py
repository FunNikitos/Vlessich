"""stage-11: billing — plans + orders + subscriptions.last_order_id

Adds Telegram Stars billing surface:

* ``plans`` — fixed SKU catalog (1m/3m/12m), seeded by API on startup.
* ``orders`` — purchase lifecycle (PENDING → PAID → REFUNDED, or FAILED).
  Partial unique index ``ix_orders_one_pending_per_user`` enforces at
  most one outstanding invoice per user at a time.
* ``subscriptions.last_order_id`` — nullable FK to orders, set on each
  successful payment so admin refund can REVOKE the subscription only
  when the refunded order is the one that paid for the current expiry.

Revision ID: 0006_stage11
Revises: 0005_stage9
Create Date: 2026-04-22 16:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_stage11"
down_revision: str | None = "0005_stage9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("price_xtr", sa.Integer(), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=8),
            nullable=False,
            server_default="XTR",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("code", name="uq_plans_code"),
        sa.CheckConstraint("duration_days > 0", name="ck_plans_duration_pos"),
        sa.CheckConstraint("price_xtr > 0", name="ck_plans_price_pos"),
    )

    op.create_table(
        "orders",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.tg_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_code", sa.String(length=16), nullable=False),
        sa.Column("amount_xtr", sa.Integer(), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=8),
            nullable=False,
            server_default="XTR",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("invoice_payload", sa.Text(), nullable=False),
        sa.Column(
            "telegram_payment_charge_id", sa.String(length=255), nullable=True
        ),
        sa.Column(
            "provider_payment_charge_id", sa.String(length=255), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "refunded_by_admin_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','PAID','REFUNDED','FAILED')",
            name="ck_orders_status",
        ),
        sa.CheckConstraint("amount_xtr > 0", name="ck_orders_amount_pos"),
    )
    op.create_index(
        "ix_orders_one_pending_per_user",
        "orders",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "ix_orders_user_created",
        "orders",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_orders_telegram_charge_id",
        "orders",
        ["telegram_payment_charge_id"],
        unique=True,
        postgresql_where=sa.text("telegram_payment_charge_id IS NOT NULL"),
    )

    op.add_column(
        "subscriptions",
        sa.Column(
            "last_order_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "last_order_id")
    op.drop_index("ix_orders_telegram_charge_id", table_name="orders")
    op.drop_index("ix_orders_user_created", table_name="orders")
    op.drop_index("ix_orders_one_pending_per_user", table_name="orders")
    op.drop_table("orders")
    op.drop_table("plans")
