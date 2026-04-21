"""admin: admin_users (rbac) + admin_login_attempts

Revision ID: 0002_admin
Revises: 0001_init
Create Date: 2026-04-21 12:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_admin"
down_revision: str | None = "0001_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "admin_users",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.dialects.postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('superadmin','support','readonly')", name="admin_users_role_chk"
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','DISABLED')", name="admin_users_status_chk"
        ),
    )

    op.create_table(
        "admin_login_attempts",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.dialects.postgresql.CITEXT(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("ip_hash", sa.CHAR(64), nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_admin_login_email_at", "admin_login_attempts", ["email", "at"]
    )


def downgrade() -> None:
    op.drop_index("ix_admin_login_email_at", table_name="admin_login_attempts")
    op.drop_table("admin_login_attempts")
    op.drop_table("admin_users")
