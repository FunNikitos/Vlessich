"""stage-7: node_health_probes.probe_source

Adds ``probe_source`` column (varchar(16) NOT NULL DEFAULT 'edge') to
``node_health_probes`` so we can distinguish control-plane TCP probes
('edge') from residential RU-proxy probes ('ru'). Existing rows are
back-filled to 'edge'. Index for source-filtered queries.

Revision ID: 0004_stage7
Revises: 0003_stage4
Create Date: 2026-04-21 17:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_stage7"
down_revision: str | None = "0003_stage4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "node_health_probes",
        sa.Column(
            "probe_source",
            sa.String(length=16),
            nullable=False,
            server_default="edge",
        ),
    )
    op.create_check_constraint(
        "node_probes_source_chk",
        "node_health_probes",
        "probe_source IN ('edge','ru')",
    )
    op.create_index(
        "ix_node_probes_node_source_probed_at",
        "node_health_probes",
        ["node_id", "probe_source", "probed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_node_probes_node_source_probed_at", table_name="node_health_probes"
    )
    op.drop_constraint(
        "node_probes_source_chk", "node_health_probes", type_="check"
    )
    op.drop_column("node_health_probes", "probe_source")
