"""stage-12: smart-routing + ruleset sources/snapshots + subscription routing_profile

Adds the smart-routing storage layer + per-subscription profile selector:

* ``ruleset_sources`` — CRUD'able list of external (antifilter, v2fly
  geosite) and local ("custom") ruleset feeds. Puller worker iterates
  enabled sources and fetches them every ``API_RULESET_PULL_INTERVAL_SEC``.
* ``ruleset_snapshots`` — versioned raw payloads keyed by
  ``(source_id, sha256)`` so identical re-pulls do not produce rows.
  ``is_current`` partial-unique index guarantees exactly one snapshot
  per source is marked current.
* ``subscriptions.routing_profile`` — enum-like string column controlling
  whether the sub payload is built with RU-direct and/or ads-block rules
  (``full`` / ``smart`` / ``adblock`` / ``plain``). Default ``plain`` so
  pre-Stage-12 subs keep their legacy behaviour.

Revision ID: 0007_stage12
Revises: 0006_stage11
Create Date: 2026-04-22 19:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_stage12"
down_revision: str | None = "0006_stage11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ruleset_sources",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "category",
            sa.String(length=32),
            nullable=False,
            server_default="ru",
        ),
        sa.Column(
            "is_enabled",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_pulled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("name", name="uq_ruleset_sources_name"),
        sa.CheckConstraint(
            "kind IN ('antifilter','v2fly_geosite','custom')",
            name="ck_ruleset_sources_kind",
        ),
        sa.CheckConstraint(
            "category IN ('ru','ads')",
            name="ck_ruleset_sources_category",
        ),
        sa.CheckConstraint(
            "(kind = 'custom') OR (url IS NOT NULL)",
            name="ck_ruleset_sources_url_required",
        ),
    )

    op.create_table(
        "ruleset_snapshots",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "source_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ruleset_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("domain_count", sa.Integer(), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("domain_count >= 0", name="ck_ruleset_snapshots_count_nonneg"),
    )
    op.create_index(
        "ix_ruleset_snapshots_source_sha",
        "ruleset_snapshots",
        ["source_id", "sha256"],
        unique=True,
    )
    op.create_index(
        "ix_ruleset_snapshots_current",
        "ruleset_snapshots",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )
    op.create_index(
        "ix_ruleset_snapshots_source_fetched",
        "ruleset_snapshots",
        ["source_id", "fetched_at"],
    )

    op.add_column(
        "subscriptions",
        sa.Column(
            "routing_profile",
            sa.String(length=16),
            nullable=False,
            server_default="plain",
        ),
    )
    op.create_check_constraint(
        "ck_subscriptions_routing_profile",
        "subscriptions",
        "routing_profile IN ('full','smart','adblock','plain')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_subscriptions_routing_profile",
        "subscriptions",
        type_="check",
    )
    op.drop_column("subscriptions", "routing_profile")
    op.drop_index(
        "ix_ruleset_snapshots_source_fetched", table_name="ruleset_snapshots"
    )
    op.drop_index(
        "ix_ruleset_snapshots_current", table_name="ruleset_snapshots"
    )
    op.drop_index(
        "ix_ruleset_snapshots_source_sha", table_name="ruleset_snapshots"
    )
    op.drop_table("ruleset_snapshots")
    op.drop_table("ruleset_sources")
