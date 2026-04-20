"""init: full Stage-0 schema (users, codes, subscriptions, devices, trials, nodes, mtproto_secrets, audit_log, code_attempts, reminder_log)

Revision ID: 0001_init
Revises:
Create Date: 2026-04-20 11:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgcrypto for gen_random_uuid()
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("tg_id", sa.BigInteger(), primary_key=True),
        sa.Column("tg_username", sa.Text(), nullable=True),
        sa.Column("lang", sa.String(8), nullable=False, server_default="ru"),
        sa.Column("phone_e164", sa.String(20), nullable=True),
        sa.Column("referral_source", sa.Text(), nullable=True),
        sa.Column("fingerprint_hash", sa.CHAR(64), nullable=True),
        sa.Column(
            "referrer_id",
            sa.BigInteger(),
            sa.ForeignKey("users.tg_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "banned", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ------------------------------------------------------------------
    # nodes
    # ------------------------------------------------------------------
    op.create_table(
        "nodes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("hostname", sa.Text(), nullable=False, unique=True),
        sa.Column("current_ip", sa.String(45), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="HEALTHY"
        ),
        sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('HEALTHY','BURNED','MAINTENANCE')", name="nodes_status_chk"
        ),
    )

    # ------------------------------------------------------------------
    # codes
    # ------------------------------------------------------------------
    op.create_table(
        "codes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code_enc", sa.LargeBinary(), nullable=False),
        sa.Column("code_hash", sa.CHAR(64), nullable=False, unique=True),
        sa.Column("plan_name", sa.Text(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("devices_limit", sa.Integer(), nullable=False),
        sa.Column("traffic_limit_gb", sa.Integer(), nullable=True),
        sa.Column(
            "allowed_locations",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "adblock_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "smart_routing_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "single_use",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("reserved_for_tg_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="ACTIVE"
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("tag", sa.Text(), nullable=True),
        sa.Column("price_rub", sa.Numeric(10, 2), nullable=True),
        sa.Column("payment_method", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "activated_by_user",
            sa.BigInteger(),
            sa.ForeignKey("users.tg_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE','USED','REVOKED','EXPIRED')",
            name="codes_status_chk",
        ),
    )

    # ------------------------------------------------------------------
    # subscriptions
    # ------------------------------------------------------------------
    op.create_table(
        "subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.tg_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "code_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("codes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "current_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nodes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("plan", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("devices_limit", sa.Integer(), nullable=False),
        sa.Column("traffic_limit_gb", sa.Integer(), nullable=True),
        sa.Column(
            "traffic_used_gb",
            sa.Numeric(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("adblock", sa.Boolean(), nullable=False),
        sa.Column("smart_routing", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sub_url_token", sa.Text(), nullable=False, unique=True),
        sa.Column("remna_user_id", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE','TRIAL','EXPIRED','REVOKED')",
            name="subscriptions_status_chk",
        ),
    )
    # Partial unique index: 1 active/trial subscription per user (TZ §4.5).
    op.create_index(
        "ix_subscriptions_one_active_per_user",
        "subscriptions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('ACTIVE','TRIAL')"),
    )

    # ------------------------------------------------------------------
    # devices
    # ------------------------------------------------------------------
    op.create_table(
        "devices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("xray_uuid_enc", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_hash", sa.CHAR(64), nullable=True),
    )

    # ------------------------------------------------------------------
    # trials
    # ------------------------------------------------------------------
    op.create_table(
        "trials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tg_id",
            sa.BigInteger(),
            sa.ForeignKey("users.tg_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "fingerprint_hash", sa.CHAR(64), nullable=False, unique=True
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ip_hash", sa.CHAR(64), nullable=True),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ------------------------------------------------------------------
    # mtproto_secrets
    # ------------------------------------------------------------------
    op.create_table(
        "mtproto_secrets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("secret_hex", sa.CHAR(64), nullable=False, unique=True),
        sa.Column("cloak_domain", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(8), nullable=False),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.tg_id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="ACTIVE"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope IN ('shared','user')", name="mtproto_scope_chk"
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','ROTATED','REVOKED')", name="mtproto_status_chk"
        ),
        sa.CheckConstraint(
            "(scope = 'shared' AND user_id IS NULL) OR "
            "(scope = 'user' AND user_id IS NOT NULL)",
            name="mtproto_scope_user_consistency",
        ),
    )

    # ------------------------------------------------------------------
    # audit_log
    # ------------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_ref", sa.Text(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "actor_type IN ('system','admin','user','bot')",
            name="audit_actor_type_chk",
        ),
    )
    op.create_index("ix_audit_at", "audit_log", ["at"])
    op.create_index("ix_audit_action", "audit_log", ["action"])

    # ------------------------------------------------------------------
    # code_attempts
    # ------------------------------------------------------------------
    op.create_table(
        "code_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("code_hash_attempted", sa.CHAR(64), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("ip_hash", sa.CHAR(64), nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "result IN ('ok','bad','rl','expired','used','reserved')",
            name="code_attempt_result_chk",
        ),
    )
    op.create_index(
        "ix_code_attempts_tg_at", "code_attempts", ["tg_id", "at"]
    )

    # ------------------------------------------------------------------
    # reminder_log
    # ------------------------------------------------------------------
    op.create_table(
        "reminder_log",
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("bucket", sa.String(4), primary_key=True),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "bucket IN ('24h','6h','1h')", name="reminder_bucket_chk"
        ),
    )


def downgrade() -> None:
    op.drop_table("reminder_log")
    op.drop_index("ix_code_attempts_tg_at", table_name="code_attempts")
    op.drop_table("code_attempts")
    op.drop_index("ix_audit_action", table_name="audit_log")
    op.drop_index("ix_audit_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("mtproto_secrets")
    op.drop_table("trials")
    op.drop_table("devices")
    op.drop_index(
        "ix_subscriptions_one_active_per_user", table_name="subscriptions"
    )
    op.drop_table("subscriptions")
    op.drop_table("codes")
    op.drop_table("nodes")
    op.drop_table("users")
