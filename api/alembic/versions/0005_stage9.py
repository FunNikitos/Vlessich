"""stage-9: per-user MTProto pool (FREE/ACTIVE/REVOKED) with port binding

Pivots Stage 8's ``MtprotoSecret`` table from a single-row shared
pool into a multi-row per-user pool. New rows pre-seeded with
``status='FREE'`` and bound to a port; allocator flips them to
``ACTIVE`` under ``SELECT FOR UPDATE SKIP LOCKED``.

Schema deltas:

* ``port INTEGER`` column.
* ``status`` CHECK extended with ``'FREE'``.
* ``mtproto_scope_user_consistency`` rewritten to allow FREE
  (scope='user', user_id IS NULL).
* New CHECK ``mtproto_port_range`` (1..65535 when set).
* New CHECK ``mtproto_user_port_consistency`` (port required for
  scope='user').
* New CHECK ``mtproto_user_status_consistency`` (no ROTATED rows
  for scope='user').
* New CHECK ``mtproto_free_no_user`` (FREE rows must not carry
  user_id).
* Partial unique ``ux_mtproto_user_active`` on ``user_id`` for
  ACTIVE+user rows (1 ACTIVE per user).
* Partial unique ``ux_mtproto_port_live`` on ``port`` for
  FREE+ACTIVE+user rows (1 live secret per port; REVOKED rows are
  tombstones and may coexist).

Safe upgrade: scope='user' rows never existed before Stage 9
(Stage 8 returned 501 for that branch).

Revision ID: 0005_stage9
Revises: 0004_stage7
Create Date: 2026-04-22 14:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_stage9"
down_revision: str | None = "0004_stage7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mtproto_secrets",
        sa.Column("port", sa.Integer(), nullable=True),
    )

    # Replace the old status CHECK with one that includes FREE.
    op.drop_constraint(
        "mtproto_status_chk", "mtproto_secrets", type_="check"
    )
    op.create_check_constraint(
        "mtproto_status_chk",
        "mtproto_secrets",
        "status IN ('ACTIVE','ROTATED','REVOKED','FREE')",
    )

    # Replace scope/user-consistency to admit FREE rows under scope='user'.
    op.drop_constraint(
        "mtproto_scope_user_consistency", "mtproto_secrets", type_="check"
    )
    op.create_check_constraint(
        "mtproto_scope_user_consistency",
        "mtproto_secrets",
        "(scope = 'shared' AND user_id IS NULL) OR ("
        "scope = 'user' AND ("
        "(status = 'FREE' AND user_id IS NULL) OR "
        "(status <> 'FREE' AND user_id IS NOT NULL)"
        "))",
    )

    op.create_check_constraint(
        "mtproto_port_range",
        "mtproto_secrets",
        "port IS NULL OR (port BETWEEN 1 AND 65535)",
    )
    op.create_check_constraint(
        "mtproto_user_port_consistency",
        "mtproto_secrets",
        "(scope = 'shared' AND port IS NULL) OR (scope = 'user' AND port IS NOT NULL)",
    )
    op.create_check_constraint(
        "mtproto_user_status_consistency",
        "mtproto_secrets",
        "scope = 'shared' OR status IN ('ACTIVE','REVOKED','FREE')",
    )
    op.create_check_constraint(
        "mtproto_free_no_user",
        "mtproto_secrets",
        "status <> 'FREE' OR user_id IS NULL",
    )

    op.create_index(
        "ux_mtproto_user_active",
        "mtproto_secrets",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE' AND scope = 'user'"),
    )
    op.create_index(
        "ux_mtproto_port_live",
        "mtproto_secrets",
        ["port"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('ACTIVE','FREE') AND scope = 'user'"
        ),
    )


def downgrade() -> None:
    op.drop_index("ux_mtproto_port_live", table_name="mtproto_secrets")
    op.drop_index("ux_mtproto_user_active", table_name="mtproto_secrets")
    op.drop_constraint("mtproto_free_no_user", "mtproto_secrets", type_="check")
    op.drop_constraint(
        "mtproto_user_status_consistency", "mtproto_secrets", type_="check"
    )
    op.drop_constraint(
        "mtproto_user_port_consistency", "mtproto_secrets", type_="check"
    )
    op.drop_constraint("mtproto_port_range", "mtproto_secrets", type_="check")
    op.drop_constraint(
        "mtproto_scope_user_consistency", "mtproto_secrets", type_="check"
    )
    op.create_check_constraint(
        "mtproto_scope_user_consistency",
        "mtproto_secrets",
        "(scope = 'shared' AND user_id IS NULL) OR (scope = 'user' AND user_id IS NOT NULL)",
    )
    op.drop_constraint("mtproto_status_chk", "mtproto_secrets", type_="check")
    op.create_check_constraint(
        "mtproto_status_chk",
        "mtproto_secrets",
        "status IN ('ACTIVE','ROTATED','REVOKED')",
    )
    op.drop_column("mtproto_secrets", "port")
