"""SQLAlchemy ORM models (TZ §12).

Stage 0 schema: includes all entities required for Stage 1 (trials, codes
activation, MTProto issuance, reminders, audit log).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Users / phone capture / referrals
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tg_username: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(8), default="ru", nullable=False)
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    referral_source: Mapped[str | None] = mapped_column(Text)
    fingerprint_hash: Mapped[str | None] = mapped_column(CHAR(64))
    referrer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="SET NULL")
    )
    banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Nodes (FI-01, future regions)
# ---------------------------------------------------------------------------
class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('HEALTHY','BURNED','MAINTENANCE')", name="nodes_status_chk"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    hostname: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    current_ip: Mapped[str | None] = mapped_column(String(45))  # IPv4/IPv6
    provider: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="HEALTHY")
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Node health probes (Stage 4 T1) — append-only log for dashboard + SLO view
# ---------------------------------------------------------------------------
class NodeHealthProbe(Base):
    __tablename__ = "node_health_probes"
    __table_args__ = (
        Index("ix_node_probes_node_probed_at", "node_id", "probed_at"),
        Index(
            "ix_node_probes_node_source_probed_at",
            "node_id",
            "probe_source",
            "probed_at",
        ),
        CheckConstraint(
            "probe_source IN ('edge','ru')", name="node_probes_source_chk"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    probed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    # Stage 7: which prober backend produced this row.
    # 'edge' = control-plane TCP probe (default, drives BURN state).
    # 'ru'   = residential RU proxy probe (telemetry only).
    probe_source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="edge", server_default="edge"
    )


# ---------------------------------------------------------------------------
# Codes (admin-issued, hash-indexed for O(log N) resolution)
# ---------------------------------------------------------------------------
class Code(Base):
    __tablename__ = "codes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE','USED','REVOKED','EXPIRED')", name="codes_status_chk"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Encrypted plaintext (libsodium secretbox); decrypted only at issuance.
    code_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # sha256(plaintext) — unique index for fast lookup without full-scan decrypt.
    code_hash: Mapped[str] = mapped_column(CHAR(64), unique=True, nullable=False)
    plan_name: Mapped[str] = mapped_column(Text, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    devices_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    traffic_limit_gb: Mapped[int | None] = mapped_column(Integer)
    allowed_locations: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    adblock_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    smart_routing_default: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    single_use: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reserved_for_tg_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    note: Mapped[str | None] = mapped_column(Text)
    tag: Mapped[str | None] = mapped_column(Text)
    price_rub: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    payment_method: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    activated_by_user: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="SET NULL")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Subscriptions (1 ACTIVE per user_id — partial unique index)
# ---------------------------------------------------------------------------
class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE','TRIAL','EXPIRED','REVOKED')",
            name="subscriptions_status_chk",
        ),
        Index(
            "ix_subscriptions_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('ACTIVE','TRIAL')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), nullable=False
    )
    code_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("codes.id", ondelete="SET NULL")
    )
    current_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="SET NULL")
    )
    plan: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    devices_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    traffic_limit_gb: Mapped[int | None] = mapped_column(Integer)
    traffic_used_gb: Mapped[Decimal] = mapped_column(
        Numeric, server_default=text("0"), nullable=False
    )
    adblock: Mapped[bool] = mapped_column(Boolean, nullable=False)
    smart_routing: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sub_url_token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    remna_user_id: Mapped[str | None] = mapped_column(Text)

    devices: Mapped[list["Device"]] = relationship(back_populates="subscription")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(Text)
    xray_uuid_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_hash: Mapped[str | None] = mapped_column(CHAR(64))

    subscription: Mapped[Subscription] = relationship(back_populates="devices")


# ---------------------------------------------------------------------------
# Trials (1 per tg_id, 1 per fingerprint)
# ---------------------------------------------------------------------------
class Trial(Base):
    __tablename__ = "trials"
    __table_args__ = (
        UniqueConstraint("tg_id", name="trials_tg_id_uniq"),
        UniqueConstraint("fingerprint_hash", name="trials_fingerprint_uniq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tg_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), nullable=False
    )
    fingerprint_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    ip_hash: Mapped[str | None] = mapped_column(CHAR(64))
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# MTProto secrets pool (shared + per-user)
# ---------------------------------------------------------------------------
class MtprotoSecret(Base):
    __tablename__ = "mtproto_secrets"
    __table_args__ = (
        CheckConstraint("scope IN ('shared','user')", name="mtproto_scope_chk"),
        CheckConstraint(
            "status IN ('ACTIVE','ROTATED','REVOKED')", name="mtproto_status_chk"
        ),
        CheckConstraint(
            "(scope = 'shared' AND user_id IS NULL) OR (scope = 'user' AND user_id IS NOT NULL)",
            name="mtproto_scope_user_consistency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    secret_hex: Mapped[str] = mapped_column(CHAR(64), unique=True, nullable=False)
    cloak_domain: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(8), nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Audit log (every mutating action)
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('system','admin','user','bot')",
            name="audit_actor_type_chk",
        ),
        Index("ix_audit_at", "at"),
        Index("ix_audit_action", "action"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_ref: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Code attempts (rate-limit & audit, including failed)
# ---------------------------------------------------------------------------
class CodeAttempt(Base):
    __tablename__ = "code_attempts"
    __table_args__ = (
        CheckConstraint(
            "result IN ('ok','bad','rl','expired','used','reserved')",
            name="code_attempt_result_chk",
        ),
        Index("ix_code_attempts_tg_at", "tg_id", "at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    code_hash_attempted: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(CHAR(64))
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Reminder log (idempotency for expiry reminders)
# ---------------------------------------------------------------------------
class ReminderLog(Base):
    __tablename__ = "reminder_log"
    __table_args__ = (
        CheckConstraint("bucket IN ('24h','6h','1h')", name="reminder_bucket_chk"),
    )

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    bucket: Mapped[str] = mapped_column(String(4), primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Admin users (RBAC) + login attempts (Stage 2 T4)
# ---------------------------------------------------------------------------
class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('superadmin','support','readonly')", name="admin_users_role_chk"
        ),
        CheckConstraint(
            "status IN ('ACTIVE','DISABLED')", name="admin_users_status_chk"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminLoginAttempt(Base):
    __tablename__ = "admin_login_attempts"
    __table_args__ = (Index("ix_admin_login_email_at", "email", "at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(CHAR(64))
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
