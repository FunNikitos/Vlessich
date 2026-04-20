"""SQLAlchemy ORM models (subset for skeleton; see TZ §12 for full schema)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tg_username: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(8), default="ru")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fingerprint_hash: Mapped[str | None] = mapped_column(Text)
    referrer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.tg_id")
    )


class Code(Base):
    __tablename__ = "codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    plan_name: Mapped[str] = mapped_column(Text, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    devices_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    traffic_limit_gb: Mapped[int | None] = mapped_column(Integer)
    allowed_locations: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    adblock_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    smart_routing_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    single_use: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reserved_for_tg_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    tag: Mapped[str | None] = mapped_column(Text)
    price_rub: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    payment_method: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    activated_by_user: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.tg_id")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id"), nullable=False
    )
    code_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("codes.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    devices_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    traffic_limit_gb: Mapped[int | None] = mapped_column(Integer)
    traffic_used_gb: Mapped[Decimal] = mapped_column(
        Numeric, default=Decimal("0"), nullable=False
    )
    adblock: Mapped[bool] = mapped_column(Boolean, nullable=False)
    smart_routing: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    sub_url_token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

    devices: Mapped[list["Device"]] = relationship(back_populates="subscription")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(Text)
    xray_uuid_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_hash: Mapped[str | None] = mapped_column(Text)

    subscription: Mapped[Subscription] = relationship(back_populates="devices")
