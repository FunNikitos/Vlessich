"""stage-4: node_health_probes table

Revision ID: 0003_stage4
Revises: 0002_admin
Create Date: 2026-04-22 08:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_stage4"
down_revision: str | None = "0002_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "node_health_probes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "probed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_node_probes_node_probed_at",
        "node_health_probes",
        ["node_id", "probed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_node_probes_node_probed_at", table_name="node_health_probes"
    )
    op.drop_table("node_health_probes")
